import sqlite3
import shutil
from datetime import datetime

DB_FILE = "qr_data.db"

def run_ultimate_janitor():
    print("🧹 Starting the Ultimate State-Aware Janitor...")

    # 1. Create a safety backup
    backup_name = f"qr_data_backup_before_cleanup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(DB_FILE, backup_name)
    print(f"📦 Created safety backup: {backup_name}\n")

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # ==========================================
        # PART 1: REBUILD THE LOGICAL STATE
        # ==========================================
        cursor.execute("SELECT * FROM qr_records ORDER BY id ASC")
        original_records = cursor.fetchall()

        cursor.execute("SELECT * FROM qr_mutations ORDER BY id ASC")
        mutations = cursor.fetchall()
        
        records_state = {}
        for r in original_records:
            records_state[r['id']] = {
                'id': r['id'],
                'qr_string': r['qr_string'],
                'original_string': r['qr_string'],
                'status': 'ACTIVE'
            }

        # Fast-forward through the timeline to find the FINAL string of every record
        for m in mutations:
            rec_id = m['record_id']
            if rec_id in records_state:
                if m['action'] == 'DELETE':
                    records_state[rec_id]['status'] = 'DELETED'
                elif m['action'] == 'EDIT':
                    records_state[rec_id]['status'] = 'EDITED'
                    records_state[rec_id]['qr_string'] = m['new_string']
                elif m['action'] == 'RESTORE':
                    is_edited = records_state[rec_id]['qr_string'] != records_state[rec_id]['original_string']
                    records_state[rec_id]['status'] = 'EDITED' if is_edited else 'ACTIVE'

        # ==========================================
        # PART 2: FIND LOGICAL COLLISIONS
        # ==========================================
        # Group by the exact, case-sensitive FINAL string
        string_groups = {}
        for rec in records_state.values():
            final_string = rec['qr_string']
            if final_string not in string_groups:
                string_groups[final_string] = []
            string_groups[final_string].append(rec['id'])

        duplicates_found = False
        for qr_string, ids in string_groups.items():
            if len(ids) > 1:
                duplicates_found = True
                ids.sort() # Oldest ID becomes the keeper
                keeper_id = ids[0]
                duplicate_ids = ids[1:]

                print(f"  -> Fixing collision for '{qr_string}': Keeping ID {keeper_id}, Removing IDs {duplicate_ids}")

                # Move all timeline events to the keeper
                for dup_id in duplicate_ids:
                    cursor.execute("UPDATE qr_mutations SET record_id = ? WHERE record_id = ?", (keeper_id, dup_id))
                    cursor.execute("DELETE FROM qr_records WHERE id = ?", (dup_id,))

        if not duplicates_found:
            print("✨ No logical duplicates found in the final state!")

        # ==========================================
        # PART 3: SWEEP REDUNDANT MUTATIONS
        # ==========================================
        # Now that timelines are merged, we might have back-to-back Deletes/Restores. Let's clean them!
        print("\n🧹 Sweeping qr_mutations for redundant actions...")
        cursor.execute("SELECT * FROM qr_mutations ORDER BY record_id ASC, id ASC")
        all_mutations = cursor.fetchall()

        mutations_to_delete = []
        current_mut_state = {}

        for m in all_mutations:
            rec_id = m['record_id']
            action = m['action']
            mut_id = m['id']

            if rec_id not in current_mut_state:
                current_mut_state[rec_id] = 'ACTIVE'

            is_redundant = False
            if action == 'DELETE' and current_mut_state[rec_id] == 'DELETED':
                is_redundant = True
            elif action == 'RESTORE' and current_mut_state[rec_id] == 'ACTIVE':
                is_redundant = True
            elif action == 'EDIT':
                current_mut_state[rec_id] = 'EDITED'

            if is_redundant:
                mutations_to_delete.append(mut_id)
            else:
                if action == 'DELETE':
                    current_mut_state[rec_id] = 'DELETED'
                elif action == 'RESTORE':
                    current_mut_state[rec_id] = 'ACTIVE'

        if mutations_to_delete:
            print(f"🗑️ Found {len(mutations_to_delete)} redundant mutation(s). Removing them...")
            for mut_id in mutations_to_delete:
                cursor.execute("DELETE FROM qr_mutations WHERE id = ?", (mut_id,))
        else:
            print("✨ qr_mutations is perfectly clean!")

        conn.commit()
        print("\n✅ Ultimate Cleanup complete! Your database is truly pristine.")

    except Exception as e:
        print(f"❌ Error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    run_ultimate_janitor()
