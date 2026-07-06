#!/usr/bin/env python3
"""
Проверяет наличие резервной копии employees.json и предлагает восстановление.
"""

import json
import os

EMPLOYEES_FILE = os.path.join(os.path.dirname(__file__), "employees.json")
BACKUP_FILE = EMPLOYEES_FILE.replace('.json', '.backup.json')

print("🔍 Проверяю резервную копию...\n")

# Проверяем текущий файл
with open(EMPLOYEES_FILE, encoding='utf-8') as f:
    current = json.load(f)

print(f"📄 Текущий файл employees.json:")
print(f"  Сотрудников: {len(current)}")
if current:
    for uid, name in current.items():
        print(f"    • {name}")

# Проверяем резервную копию
if os.path.exists(BACKUP_FILE):
    with open(BACKUP_FILE, encoding='utf-8') as f:
        backup = json.load(f)

    print(f"\n💾 Найдена резервная копия!")
    print(f"  Сотрудников в резервной копии: {len(backup)}")
    if backup:
        for uid, name in backup.items():
            print(f"    • {name}")

    if len(backup) > len(current):
        print(f"\n✅ Резервная копия содержит больше данных ({len(backup)} > {len(current)})")

        response = input("\n🔄 Восстановить из резервной копии? (y/n): ").strip().lower()
        if response == 'y':
            with open(EMPLOYEES_FILE, 'w', encoding='utf-8') as f:
                json.dump(backup, f, ensure_ascii=False, indent=2)
            print("✅ Восстановлено!")
            print(f"\nВосстановлено сотрудников:")
            for uid, name in backup.items():
                print(f"  ✓ {name}")
        else:
            print("❌ Восстановление отменено")
    else:
        print("\n⚠️  Резервная копия не лучше текущего файла")
else:
    print(f"\n❌ Резервной копии не найдено: {BACKUP_FILE}")
    print("💡 Используй скрипты restore_employees.py или recreate_employees.py")
