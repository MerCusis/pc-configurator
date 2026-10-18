"""Этап 3: расчёт мощности и правила совместимости. Без БД, на демо-деталях seed."""
import json
from decimal import Decimal

import pytest

from app.models.enums import Severity
from app.seed_data import PARTS, RULES
from app.services.build_check import normalize_items
from app.services.compatibility import RULE_CODES, RuleConfig, check_build
from app.services.parts import BuildPart
from app.services.power import estimate_power, suggest_psu

_BY_KEY = {p["key"]: (i + 1, p) for i, p in enumerate(PARTS)}

# Совместимая сборка: пик 270 Вт, рекомендация 550 Вт (RTX 4060), БП 650 Вт
BASE = {
    "cpu": "amd-ryzen5-7600",
    "motherboard": "msi-b650-gaming-plus-wifi",
    "ram": "kingston-fury-ddr5-32-6000",
    "gpu": "palit-rtx4060-dual",
    "storage": "samsung-990pro-1tb",
    "psu": "deepcool-pk650d",
    "case": "bequiet-pure-base-500",
    "cooler": "deepcool-ak400",
}


def P(key, qty=1, **specs):
    pid, item = _BY_KEY[key]
    merged = {k: v for k, v in {**item["specs"], **specs}.items() if v is not None}
    return BuildPart(pid, item["category"], item["name"], merged, item["power_w"], qty, Decimal(str(item["price"])))


def make(**override):
    """make(case="fractal-terra", gpu=None, storage=[("kingston-nv2-2tb", 2)])"""
    slots = {**BASE, **override}
    parts = []
    for value in slots.values():
        if value is None:
            continue
        for entry in value if isinstance(value, list) else [value]:
            parts.append(P(*entry) if isinstance(entry, tuple) else P(entry))
    return parts


def check(parts, **rules):
    cfg = {code: RuleConfig(code, **kw) for code, kw in rules.items()} if rules else None
    return check_build(parts, cfg)


def codes(result, severity=None):
    return {i.code for i in result.issues if severity is None or i.severity == severity}


E, W = Severity.ERROR, Severity.WARNING


# ---------- Мощность ----------

def test_power_base_build():
    power = check(make()).power
    assert (power.peak_w, power.recommended_w, power.suggested_psu_w, power.vendor_min_w) == (270, 550, 550, 550)
    assert power.by_category["gpu"] == 115


def test_power_margin_uses_exact_decimal_rounding():
    est = estimate_power([BuildPart(1, "cpu", "x", {}, power_w=220)])
    assert (est.peak_w, est.recommended_w, est.suggested_psu_w) == (270, 351, 400)


def test_power_counts_quantity_and_ignores_missing_power():
    est = estimate_power([BuildPart(1, "storage", "d", {}, 5, quantity=3), BuildPart(2, "case", "c", {})])
    assert est.peak_w == 50 + 15


def test_power_vendor_recommendation_dominates():
    est = estimate_power([P("asus-tuf-rtx4080s")])
    assert est.recommended_w == 850 and est.suggested_psu_w == 850


def test_suggest_psu_above_table_rounds_to_hundreds():
    assert suggest_psu(1601) == 1700
    est = estimate_power([BuildPart(1, "cpu", "x", {}, power_w=2000)])
    assert est.recommended_w == 2665 and est.suggested_psu_w == 2700


@pytest.mark.parametrize("kwargs", [{"factor": 0.9}, {"base_load_w": -1}])
def test_power_invalid_arguments(kwargs):
    with pytest.raises(ValueError):
        estimate_power([], **kwargs)


# ---------- Базовые сценарии ----------

def test_every_seed_rule_has_implementation():
    assert set(RULE_CODES) == {r["code"] for r in RULES}


def test_base_build_compatible_and_complete():
    result = check(make())
    assert result.issues == ()
    assert result.is_compatible and result.is_complete
    assert result.total_price == sum(Decimal(str(_BY_KEY[k][1]["price"])) for k in BASE.values())


def test_empty_build():
    result = check([])
    assert result.issues == () and result.power.peak_w == 50
    assert result.is_compatible and not result.is_complete


def test_missing_required_categories():
    result = check([P("amd-ryzen5-7600")])
    assert result.is_compatible and not result.is_complete
    assert {"motherboard", "ram", "storage", "psu", "case"} <= set(result.missing_categories)
    assert "gpu" not in result.missing_categories  # видеокарта необязательна


def test_result_is_json_serializable():
    data = json.loads(json.dumps(check(make(cpu="intel-i5-14400f")).to_dict(), ensure_ascii=False))
    assert data["is_compatible"] is False
    assert data["issues"][0]["severity"] == "error" and data["issues"][0]["part_ids"]


# ---------- Правила ----------

def test_socket_mismatch():
    result = check(make(cpu="intel-i5-14400f"))
    assert codes(result, E) == {"socket_mismatch"}
    issue = result.errors[0]
    assert issue.rule == "cpu_motherboard_socket" and issue.details["cpu_socket"] == "LGA1700"


def test_socket_comparison_ignores_case():
    parts = make()
    parts[1] = P("msi-b650-gaming-plus-wifi", socket="am5")
    assert check(parts).issues == ()


def test_ram_type_mismatch_with_board_and_cpu():
    assert codes(check(make(ram="kingston-fury-ddr4-16-3200")), E) == {"ram_type_motherboard", "ram_type_cpu"}


def test_ram_slots_exceeded():
    result = check(make(motherboard="asrock-b650i-lightning-wifi", ram=[("kingston-fury-ddr5-32-6000", 2)]))
    assert codes(result, E) == {"ram_slots_exceeded"}


def test_ram_capacity_and_slots_exceeded():
    result = check(make(ram=[("gskill-trident-z5-64-6000", 4)]))
    assert codes(result, E) == {"ram_slots_exceeded", "ram_capacity_exceeded"}


def test_mixed_ram_kits_is_warning_only():
    result = check(make(ram=["kingston-fury-ddr5-32-6000", "gskill-trident-z5-64-6000"]))
    assert codes(result) == {"ram_mixed_kits"} and result.is_compatible


def test_case_motherboard_form_factor():
    result = check(make(case="coolermaster-q300l"))
    assert codes(result, E) == {"case_motherboard_form_factor"}
    assert "cooler_height_tight" in codes(result, W)  # 155 мм при лимите 159 мм


def test_case_psu_form_factor():
    result = check(make(case="fractal-terra", motherboard="asrock-b650i-lightning-wifi", cooler="noctua-nh-l9a-am5"))
    assert codes(result, E) == {"case_psu_form_factor"}


def test_gpu_too_long():
    result = check(make(case="fractal-terra", motherboard="asrock-b650i-lightning-wifi",
                        cooler="noctua-nh-l9a-am5", psu="corsair-sf750", gpu="asus-tuf-rtx4080s"))
    assert codes(result, E) == {"gpu_length_exceeded"}
    assert "psu_low_headroom" in codes(result, W)


def test_gpu_tight_uses_threshold_from_params():
    parts = make(case="coolermaster-q300l", motherboard="asrock-b650i-lightning-wifi", gpu="asus-tuf-rtx4080s")
    assert "gpu_length_tight" not in codes(check(parts))  # запас 12 мм при пороге 10
    result = check(parts, case_gpu_length={"params": {"warning_margin_mm": 15}})
    assert "gpu_length_tight" in codes(result, W) and result.is_compatible


def test_cooler_too_tall():
    result = check(make(case="coolermaster-q300l", motherboard="asrock-b650i-lightning-wifi", cooler="noctua-nh-d15"))
    assert codes(result, E) == {"cooler_height_exceeded"}


def test_cooler_socket_unsupported():
    result = check(make(cpu="intel-i5-14400f", motherboard="msi-pro-z790-p-wifi", cooler="noctua-nh-l9a-am5"))
    assert codes(result, E) == {"cooler_socket_unsupported"}


def test_psu_insufficient():
    result = check(make(cpu="intel-i7-14700k", motherboard="msi-pro-z790-p-wifi",
                        gpu="asus-tuf-rtx4080s", psu="bequiet-system-power-10-550"))
    assert codes(result, E) == {"psu_insufficient"}
    assert result.errors[0].details["peak_w"] == 640


def test_psu_low_headroom_is_warning():
    result = check(make(gpu="msi-rtx4070s-ventus2x", psu="bequiet-system-power-10-550"))
    assert codes(result) == {"psu_low_headroom"} and result.is_compatible


def test_psu_factor_from_params():
    result = check(make(), psu_power={"params": {"recommended_factor": 3.0, "base_load_w": 50}})
    assert result.power.recommended_w == 810
    assert codes(result, W) == {"psu_low_headroom"}


def test_m2_slots_exceeded_is_warning_by_default():
    result = check(make(motherboard="asrock-b650i-lightning-wifi",
                        storage=[("samsung-990pro-1tb", 2), "kingston-nv2-2tb"]))
    assert codes(result) == {"m2_slots_exceeded"}
    assert result.warnings[0].rule == "storage_slots" and result.is_compatible


def test_sata_ports_exceeded():
    result = check(make(motherboard="asrock-b650i-lightning-wifi",
                        storage=[("samsung-870evo-1tb", 2), "seagate-barracuda-2tb"]))
    assert codes(result) == {"sata_ports_exceeded"}


# ---------- Неполные данные и настройки правил ----------

def test_missing_spec_skips_rule_with_warning():
    parts = make(cpu="intel-i5-14400f")
    parts[1] = P("msi-b650-gaming-plus-wifi", socket=None)
    result = check(parts)
    issue = next(i for i in result.issues if i.rule == "cpu_motherboard_socket")
    assert issue.code == "missing_specs" and issue.severity == W and issue.details == {"key": "socket"}
    assert "socket_mismatch" not in codes(result)


@pytest.mark.parametrize("bad", ["250", -1, True, float("nan")])
def test_invalid_spec_value_is_treated_as_missing(bad):
    parts = make()
    parts[3] = P("palit-rtx4060-dual", length_mm=bad)
    result = check(parts)
    assert codes(result) == {"missing_specs"} and result.is_compatible


def test_disabled_rule_is_skipped():
    result = check(make(cpu="intel-i5-14400f"), cpu_motherboard_socket={"is_enabled": False})
    assert "socket_mismatch" not in codes(result) and result.is_compatible


def test_severity_override_downgrades_error():
    result = check(make(cpu="intel-i5-14400f"), cpu_motherboard_socket={"severity": Severity.WARNING})
    assert codes(result, W) == {"socket_mismatch"} and result.is_compatible


def test_severity_override_upgrades_warning():
    result = check(make(motherboard="asrock-b650i-lightning-wifi",
                        storage=[("samsung-990pro-1tb", 2), "kingston-nv2-2tb"]),
                   storage_slots={"severity": Severity.ERROR})
    assert codes(result, E) == {"m2_slots_exceeded"}


@pytest.mark.parametrize("value", ["abc", -5, 1000, None, True])
def test_invalid_params_fall_back_to_defaults(value):
    parts = make(case="coolermaster-q300l", motherboard="asrock-b650i-lightning-wifi", gpu="asus-tuf-rtx4080s")
    result = check(parts, case_gpu_length={"params": {"warning_margin_mm": value}},
                   psu_power={"params": {"recommended_factor": value}})
    assert "gpu_length_tight" not in codes(result)
    assert result.power.factor == 1.3


def test_unknown_rule_in_config_is_ignored():
    assert check(make(), legacy_rule={}).issues == ()


def test_category_limits():
    result = check(make(cpu=["amd-ryzen5-7600", "amd-ryzen7-7800x3d"], ram=[("kingston-fury-ddr5-32-6000", 5)]))
    limit = [i for i in result.issues if i.code == "category_limit_exceeded"]
    assert {i.details["category"] for i in limit} == {"cpu", "ram"}
    assert all(i.rule == "structure" and i.severity == E for i in limit)


def test_unknown_category_is_error():
    assert "unknown_category" in codes(check([BuildPart(1, "monitor", "m", {})]), E)


# ---------- Нормализация входа ----------

def test_normalize_items_merges_duplicates():
    assert normalize_items([(5, 1), (3, 2), (5, 2)]) == {5: 3, 3: 2}


@pytest.mark.parametrize("items", [[(0, 1)], [(1, 0)], [(1, 17)], [(1, 10), (1, 7)], [("1", 1)], [(1, True)]])
def test_normalize_items_rejects_invalid(items):
    with pytest.raises(ValueError):
        normalize_items(items)
