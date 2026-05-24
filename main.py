import snap7
import pyodbc
import time
from datetime import datetime, timedelta
from snap7.util import get_bool, get_dint, get_int

# --- CONFIGURARE ---
PLC_IP = '192.168.0.1'
SQL_CONN = 'DRIVER={SQL Server};SERVER=localhost\\SQLEXPRESS01;DATABASE=FactoryTrace_DB;Trusted_Connection=yes;'

plc = snap7.client.Client()
asteptare_linii = {} # { uid: {'start': timp, 'data': bytes} }
procesate = set()

def decode_dtl(data, offset):
    try:
        year = get_int(data, offset)
        if not (2025 <= year <= 2030): return None
        # Returnăm string pentru SQL și HMI
        return f"{year}-{data[offset+2]}-{data[offset+3]} {data[offset+5]}:{data[offset+6]}:{data[offset+7]}"
    except: return None

def save_sql(query, params, msg):
    try:
        with pyodbc.connect(SQL_CONN) as conn:
            conn.cursor().execute(query, params)
            print(f"[SQL] {msg}")
    except Exception as e: print(f"Eroare SQL: {e}")

def check_trace_line(nume, db_nr, tabel):
    """Gestionează liniile Green și Blue cu logica de Timeout 25s"""
    for i in range(51):
        base = 2 + (i * 44)
        try:
            data = plc.db_read(db_nr, base, 44)
            p_id = get_dint(data, 0)
            if p_id <= 0: continue

            uid = f"{nume}_{p_id}"
            if uid in procesate: continue

            t_vis = decode_dtl(data, 18)
            t_as = decode_dtl(data, 30)

            # 1. Detectare piesa la Vision
            if t_vis and uid not in asteptare_linii:
                asteptare_linii[uid] = {'start': datetime.now(), 'data': data}
                print(f"[*] {nume} ID {p_id}: Detectat. Pornit timeout...")

            # 2. Verificare Status (OK sau Timeout)
            if uid in asteptare_linii:
                query = f"INSERT INTO {tabel} (PartID, TimeMachining, TimeVision, Vision_inspect, Time_assembly, Status) VALUES (?,?,?,?,?,?)"
                
                if t_as: # CAZ OK
                    params = (p_id, decode_dtl(data, 4), t_vis, get_bool(data, 16, 0), t_as, 1)
                    save_sql(query, params, f"{nume} ID {p_id} salvat OK")
                    procesate.add(uid)
                    del asteptare_linii[uid]

                elif datetime.now() > asteptare_linii[uid]['start'] + timedelta(seconds=25): # CAZ TIMEOUT
                    old_data = asteptare_linii[uid]['data']
                    params = (p_id, decode_dtl(old_data, 4), t_vis, get_bool(old_data, 16, 0), None, 0)
                    save_sql(query, params, f"{nume} ID {p_id} marcat TIMEOUT")
                    procesate.add(uid)
                    del asteptare_linii[uid]
        except: continue

def check_boxes():
    """Gestionează DB8 (Box) cu logica de Data Ready"""
    for i in range(11):
        base = 2 + (i * 56)
        try:
            data = plc.db_read(8, base, 56)
            b_id = get_int(data, 0)
            # Verificăm bitul Data_Ready (54.1)
            if 0 < b_id < 1000 and get_bool(data, 54, 1):
                t_exsy = decode_dtl(data, 42)
                uid = f"BOX_{b_id}_{t_exsy}"

                if uid not in procesate:
                    query = "INSERT INTO Box_Trace (BoxID, IsBox, TimeAsm, TimeAsDone, [Assembly], TimePack, Packaging, TimeExSys) VALUES (?,1,?,?,?,?,?,?)"
                    params = (
                        b_id, decode_dtl(data, 4), decode_dtl(data, 16),
                        1 if get_bool(data, 28, 0) else 0,
                        decode_dtl(data, 30), 1 if get_bool(data, 54, 0) else 0, t_exsy
                    )
                    save_sql(query, params, f"BOX ID {b_id} salvat")
                    procesate.add(uid)
        except: continue

# --- LOOP PRINCIPAL UNIFICAT ---
if __name__ == "__main__":
    print("--- Sistem Traceability Unificat Pornit ---")
    while True:
        if not plc.get_connected():
            try: plc.connect(PLC_IP, 0, 1)
            except: time.sleep(2); continue

        # Verificăm toate modulele pe rând
        check_trace_line("Green", 2, "Green_Trace")
        check_trace_line("Blue", 18, "Blue_Trace")
        check_boxes()
        
        time.sleep(1)