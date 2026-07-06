#!/usr/bin/env python3
"""
Восстанавливает employees.json с известными Telegram ID сотрудников.
Измени значения ID на реальные из вашей резервной копии.
"""

import json
import os

EMPLOYEES_FILE = os.path.join(os.path.dirname(__file__), "employees.json")

# ⬇️ Заполни реальные Telegram ID сотрудников
employees_backup = {
    "796207056": "Анна Кономенко",
    # "ID_сотрудника_2": "Дарья Вольнова",
    "1694781376": "Ксения Наныкина",  # был в логах от 17.06
    # "ID_сотрудника_3": "Валерия Папоян",
    # "ID_сотрудника_4": "Лианна Багдасарян",
    # "ID_сотрудника_5": "Алена Черкашина",
    # "ID_сотрудника_6": "Валерия Абрамова",
    # "ID_сотрудника_7": "Владислава Герасимчук",
}

print("📝 Восстанавливаю employees.json...\n")
with open(EMPLOYEES_FILE, 'w', encoding='utf-8') as f:
    json.dump(employees_backup, f, ensure_ascii=False, indent=2)

print(f"✅ Восстановлено {len(employees_backup)} сотрудников:")
for uid, name in employees_backup.items():
    print(f"  {uid} → {name}")

print("\n💡 Рекомендация: Остальные сотрудники пусть напишут боту /start в личку для регистрации.")
