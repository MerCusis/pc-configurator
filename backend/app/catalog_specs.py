"""Контракт характеристик: какие ключи specs обязательны для каждой категории.

Используется seed-данными, проверкой совместимости (этап 3) и импортом (этап 5).
Значения-словари: socket "AM5"/"LGA1700", form_factor "ATX"/"Micro-ATX"/"Mini-ITX",
memory_type "DDR4"/"DDR5", storage interface "nvme"/"sata", psu form_factor "ATX"/"SFX".
"""
REQUIRED_SPEC_KEYS: dict[str, frozenset[str]] = {
    "cpu": frozenset({"socket", "memory_types", "tdp_w", "integrated_graphics"}),
    "motherboard": frozenset(
        {"socket", "form_factor", "memory_type", "memory_slots", "max_memory_gb", "m2_slots", "sata_ports"}
    ),
    "ram": frozenset({"memory_type", "modules", "capacity_gb", "speed_mhz"}),
    "gpu": frozenset({"length_mm", "tdp_w", "recommended_psu_w"}),
    "storage": frozenset({"interface", "capacity_gb"}),
    "psu": frozenset({"wattage_w", "form_factor"}),
    "case": frozenset(
        {"motherboard_form_factors", "max_gpu_length_mm", "max_cooler_height_mm", "psu_form_factors"}
    ),
    "cooler": frozenset({"sockets", "height_mm"}),
}

# Категории, для которых power_w обязателен при импорте
POWER_REQUIRED_CATEGORIES = frozenset({"cpu", "gpu"})

# Подписи характеристик для интерфейса. Порядок словаря = порядок вывода
SPEC_LABELS: dict[str, str] = {
    "socket": "Сокет",
    "sockets": "Поддерживаемые сокеты",
    "form_factor": "Форм-фактор",
    "memory_type": "Тип памяти",
    "memory_types": "Типы памяти",
    "memory_slots": "Слоты памяти",
    "max_memory_gb": "Макс. объём памяти",
    "modules": "Модулей в комплекте",
    "capacity_gb": "Объём",
    "speed_mhz": "Частота",
    "interface": "Интерфейс",
    "m2_slots": "Слоты M.2",
    "sata_ports": "Порты SATA",
    "tdp_w": "TDP",
    "integrated_graphics": "Встроенная графика",
    "length_mm": "Длина",
    "recommended_psu_w": "Рекомендуемый БП",
    "wattage_w": "Мощность",
    "motherboard_form_factors": "Форм-факторы плат",
    "max_gpu_length_mm": "Макс. длина видеокарты",
    "max_cooler_height_mm": "Макс. высота кулера",
    "psu_form_factors": "Форм-факторы БП",
    "height_mm": "Высота",
}
