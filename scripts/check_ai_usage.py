#!/usr/bin/env python3
"""Quick script to check ai_usage_log table"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.db.database import DatabaseManager

def check_usage():
    with DatabaseManager() as db:
        # Count records
        db.cursor.execute("SELECT COUNT(*) as count FROM ai_usage_log")
        count = db.cursor.fetchone()['count']
        print(f"\n📊 Total registros en ai_usage_log: {count}")

        if count > 0:
            # Show last 5 records
            db.cursor.execute("""
                SELECT id, created_at, provider, model, usage_type,
                       input_tokens, output_tokens, estimated_cost_usd, response_time_ms
                FROM ai_usage_log
                ORDER BY created_at DESC
                LIMIT 5
            """)

            print("\n📝 Últimos 5 registros:")
            print("-" * 100)
            for row in db.cursor.fetchall():
                print(f"  ID: {row['id']} | {row['created_at']} | {row['provider']}/{row['model']}")
                print(f"     Tipo: {row['usage_type']} | Tokens: {row['input_tokens']}/{row['output_tokens']} | ${row['estimated_cost_usd']:.6f} | {row['response_time_ms']}ms")
                print()
        else:
            print("\n⚠️  No hay registros. Haz una búsqueda para generar datos.")

if __name__ == '__main__':
    check_usage()
