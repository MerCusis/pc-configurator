"""Стартовые данные: категории, правила и демо-каталог.

Цены демонстрационные (RUB), характеристики взяты из спецификаций производителей
и нужны для проверки совместимости. Перед production замените каталог импортом.
"""
from decimal import Decimal
from typing import Any

SEED_SOURCE = "seed"

CATEGORIES: list[dict[str, Any]] = [
    {"slug": "cpu", "name": "Процессоры", "sort_order": 10, "is_required": True, "max_items": 1},
    {"slug": "motherboard", "name": "Материнские платы", "sort_order": 20, "is_required": True, "max_items": 1},
    {"slug": "ram", "name": "Оперативная память", "sort_order": 30, "is_required": True, "max_items": 4},
    {"slug": "gpu", "name": "Видеокарты", "sort_order": 40, "is_required": False, "max_items": 1},
    {"slug": "storage", "name": "Накопители", "sort_order": 50, "is_required": True, "max_items": 8},
    {"slug": "psu", "name": "Блоки питания", "sort_order": 60, "is_required": True, "max_items": 1},
    {"slug": "case", "name": "Корпуса", "sort_order": 70, "is_required": True, "max_items": 1},
    {"slug": "cooler", "name": "Охлаждение процессора", "sort_order": 80, "is_required": False, "max_items": 1},
]

RULES: list[dict[str, Any]] = [
    {"code": "cpu_motherboard_socket", "name": "Сокет процессора и платы", "severity": "error",
     "description": "Сокет процессора совпадает с сокетом материнской платы.", "params": {}},
    {"code": "ram_motherboard", "name": "Память и материнская плата", "severity": "error",
     "description": "Тип памяти поддерживается платой и процессором, модулей не больше слотов, объём не больше максимума.",
     "params": {}},
    {"code": "case_form_factors", "name": "Корпус: форм-факторы платы и БП", "severity": "error",
     "description": "Корпус поддерживает форм-фактор материнской платы и блока питания.", "params": {}},
    {"code": "case_gpu_length", "name": "Длина видеокарты", "severity": "error",
     "description": "Видеокарта помещается в корпус. Предупреждение, если запас меньше порога.",
     "params": {"warning_margin_mm": 10}},
    {"code": "case_cooler_height", "name": "Высота кулера", "severity": "error",
     "description": "Кулер помещается в корпус по высоте. Предупреждение, если запас меньше порога.",
     "params": {"warning_margin_mm": 5}},
    {"code": "cooler_socket", "name": "Крепление кулера", "severity": "error",
     "description": "Кулер поддерживает сокет процессора.", "params": {}},
    {"code": "psu_power", "name": "Мощность блока питания", "severity": "error",
     "description": "Ошибка, если БП слабее пиковой нагрузки. Предупреждение, если меньше нагрузки с запасом.",
     "params": {"base_load_w": 50, "recommended_factor": 1.3}},
    {"code": "storage_slots", "name": "Разъёмы накопителей", "severity": "warning",
     "description": "На плате хватает слотов M.2 и портов SATA для выбранных накопителей.", "params": {}},
]

MANUFACTURERS: list[dict[str, str]] = [
    {"slug": s, "name": n}
    for s, n in [
        ("amd", "AMD"), ("intel", "Intel"), ("msi", "MSI"), ("asus", "ASUS"), ("gigabyte", "Gigabyte"),
        ("asrock", "ASRock"), ("kingston", "Kingston"), ("gskill", "G.Skill"), ("palit", "Palit"),
        ("sapphire", "Sapphire"), ("be-quiet", "be quiet!"), ("cooler-master", "Cooler Master"),
        ("fractal", "Fractal Design"), ("deepcool", "DeepCool"), ("noctua", "Noctua"),
        ("corsair", "Corsair"), ("samsung", "Samsung"), ("seagate", "Seagate"),
    ]
]

ATX_ALL = ["ATX", "Micro-ATX", "Mini-ITX"]
COMMON_SOCKETS = ["AM4", "AM5", "LGA1700"]


def _p(key: str, category: str, maker: str, name: str, price: str, specs: dict[str, Any],
       power_w: int | None = None) -> dict[str, Any]:
    return {"key": key, "category": category, "manufacturer": maker, "name": name,
            "price": Decimal(price), "power_w": power_w, "specs": specs}


PARTS: list[dict[str, Any]] = [
    # Процессоры: power_w = пиковое потребление (PPT / PL2)
    _p("amd-ryzen5-7600", "cpu", "amd", "AMD Ryzen 5 7600", "17990",
       {"socket": "AM5", "memory_types": ["DDR5"], "tdp_w": 65, "integrated_graphics": True}, 88),
    _p("amd-ryzen7-7800x3d", "cpu", "amd", "AMD Ryzen 7 7800X3D", "39990",
       {"socket": "AM5", "memory_types": ["DDR5"], "tdp_w": 120, "integrated_graphics": True}, 162),
    _p("amd-ryzen5-5600", "cpu", "amd", "AMD Ryzen 5 5600", "9990",
       {"socket": "AM4", "memory_types": ["DDR4"], "tdp_w": 65, "integrated_graphics": False}, 88),
    _p("intel-i5-14400f", "cpu", "intel", "Intel Core i5-14400F", "15990",
       {"socket": "LGA1700", "memory_types": ["DDR4", "DDR5"], "tdp_w": 65, "integrated_graphics": False}, 148),
    _p("intel-i7-14700k", "cpu", "intel", "Intel Core i7-14700K", "38990",
       {"socket": "LGA1700", "memory_types": ["DDR4", "DDR5"], "tdp_w": 125, "integrated_graphics": True}, 253),
    # Материнские платы
    _p("msi-b650-gaming-plus-wifi", "motherboard", "msi", "MSI B650 GAMING PLUS WIFI", "18990",
       {"socket": "AM5", "form_factor": "ATX", "memory_type": "DDR5", "memory_slots": 4,
        "max_memory_gb": 192, "m2_slots": 2, "sata_ports": 4}),
    _p("asrock-b650i-lightning-wifi", "motherboard", "asrock", "ASRock B650I Lightning WiFi", "19990",
       {"socket": "AM5", "form_factor": "Mini-ITX", "memory_type": "DDR5", "memory_slots": 2,
        "max_memory_gb": 96, "m2_slots": 2, "sata_ports": 2}),
    _p("gigabyte-b550m-ds3h", "motherboard", "gigabyte", "Gigabyte B550M DS3H", "8990",
       {"socket": "AM4", "form_factor": "Micro-ATX", "memory_type": "DDR4", "memory_slots": 4,
        "max_memory_gb": 128, "m2_slots": 2, "sata_ports": 4}),
    _p("asus-prime-b760m-a-d4", "motherboard", "asus", "ASUS PRIME B760M-A D4", "12990",
       {"socket": "LGA1700", "form_factor": "Micro-ATX", "memory_type": "DDR4", "memory_slots": 4,
        "max_memory_gb": 128, "m2_slots": 2, "sata_ports": 4}),
    _p("msi-pro-z790-p-wifi", "motherboard", "msi", "MSI PRO Z790-P WIFI", "21990",
       {"socket": "LGA1700", "form_factor": "ATX", "memory_type": "DDR5", "memory_slots": 4,
        "max_memory_gb": 192, "m2_slots": 4, "sata_ports": 6}),
    # Память: capacity_gb = объём комплекта
    _p("kingston-fury-ddr5-32-6000", "ram", "kingston", "Kingston FURY Beast 32 ГБ (2x16) DDR5-6000", "10990",
       {"memory_type": "DDR5", "modules": 2, "capacity_gb": 32, "speed_mhz": 6000}, 8),
    _p("gskill-trident-z5-64-6000", "ram", "gskill", "G.Skill Trident Z5 64 ГБ (2x32) DDR5-6000", "21990",
       {"memory_type": "DDR5", "modules": 2, "capacity_gb": 64, "speed_mhz": 6000}, 10),
    _p("kingston-fury-ddr4-16-3200", "ram", "kingston", "Kingston FURY Beast 16 ГБ (2x8) DDR4-3200", "3990",
       {"memory_type": "DDR4", "modules": 2, "capacity_gb": 16, "speed_mhz": 3200}, 6),
    _p("kingston-fury-ddr4-32-3200", "ram", "kingston", "Kingston FURY Beast 32 ГБ (2x16) DDR4-3200", "6990",
       {"memory_type": "DDR4", "modules": 2, "capacity_gb": 32, "speed_mhz": 3200}, 6),
    # Видеокарты
    _p("palit-rtx4060-dual", "gpu", "palit", "Palit GeForce RTX 4060 Dual", "32990",
       {"length_mm": 250, "tdp_w": 115, "recommended_psu_w": 550}, 115),
    _p("msi-rtx4070s-ventus2x", "gpu", "msi", "MSI GeForce RTX 4070 SUPER VENTUS 2X", "64990",
       {"length_mm": 242, "tdp_w": 220, "recommended_psu_w": 650}, 220),
    _p("sapphire-pulse-rx7800xt", "gpu", "sapphire", "Sapphire PULSE Radeon RX 7800 XT", "59990",
       {"length_mm": 280, "tdp_w": 263, "recommended_psu_w": 700}, 263),
    _p("asus-tuf-rtx4080s", "gpu", "asus", "ASUS TUF Gaming GeForce RTX 4080 SUPER", "119990",
       {"length_mm": 348, "tdp_w": 320, "recommended_psu_w": 850}, 320),
    # Накопители
    _p("samsung-990pro-1tb", "storage", "samsung", "Samsung 990 PRO 1 ТБ", "11990",
       {"interface": "nvme", "capacity_gb": 1000, "form_factor": "M.2 2280"}, 6),
    _p("kingston-nv2-2tb", "storage", "kingston", "Kingston NV2 2 ТБ", "11490",
       {"interface": "nvme", "capacity_gb": 2000, "form_factor": "M.2 2280"}, 4),
    _p("samsung-870evo-1tb", "storage", "samsung", "Samsung 870 EVO 1 ТБ", "8990",
       {"interface": "sata", "capacity_gb": 1000, "form_factor": "2.5"}, 3),
    _p("seagate-barracuda-2tb", "storage", "seagate", "Seagate BarraCuda 2 ТБ", "6490",
       {"interface": "sata", "capacity_gb": 2000, "form_factor": "3.5"}, 6),
    # Блоки питания
    _p("bequiet-system-power-10-550", "psu", "be-quiet", "be quiet! System Power 10 550W", "5490",
       {"wattage_w": 550, "form_factor": "ATX"}),
    _p("deepcool-pk650d", "psu", "deepcool", "DeepCool PK650D", "6290", {"wattage_w": 650, "form_factor": "ATX"}),
    _p("corsair-rm850e", "psu", "corsair", "Corsair RM850e", "12990", {"wattage_w": 850, "form_factor": "ATX"}),
    _p("corsair-sf750", "psu", "corsair", "Corsair SF750", "17990", {"wattage_w": 750, "form_factor": "SFX"}),
    # Корпуса
    _p("bequiet-pure-base-500", "case", "be-quiet", "be quiet! Pure Base 500", "8990",
       {"motherboard_form_factors": ATX_ALL, "max_gpu_length_mm": 369, "max_cooler_height_mm": 190,
        "psu_form_factors": ["ATX"]}),
    _p("deepcool-ch560", "case", "deepcool", "DeepCool CH560", "7990",
       {"motherboard_form_factors": ATX_ALL, "max_gpu_length_mm": 380, "max_cooler_height_mm": 175,
        "psu_form_factors": ["ATX"]}),
    _p("coolermaster-q300l", "case", "cooler-master", "Cooler Master MasterBox Q300L", "4490",
       {"motherboard_form_factors": ["Micro-ATX", "Mini-ITX"], "max_gpu_length_mm": 360,
        "max_cooler_height_mm": 159, "psu_form_factors": ["ATX"]}),
    _p("fractal-terra", "case", "fractal", "Fractal Design Terra", "17990",
       {"motherboard_form_factors": ["Mini-ITX"], "max_gpu_length_mm": 322, "max_cooler_height_mm": 77,
        "psu_form_factors": ["SFX"]}),
    # Охлаждение
    _p("deepcool-ak400", "cooler", "deepcool", "DeepCool AK400", "2490",
       {"sockets": COMMON_SOCKETS, "height_mm": 155}, 3),
    _p("noctua-nh-d15", "cooler", "noctua", "Noctua NH-D15", "12990", {"sockets": COMMON_SOCKETS, "height_mm": 165}, 5),
    _p("noctua-nh-l9a-am5", "cooler", "noctua", "Noctua NH-L9a-AM5", "5490",
       {"sockets": ["AM4", "AM5"], "height_mm": 37}, 2),
]
