from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from electricity_forecaster.db import connect, init_db

init_db()
with connect() as c:
    row=c.execute("SELECT run_id,issue_time FROM forecast_runs WHERE source='fingrid' ORDER BY issue_time DESC LIMIT 1").fetchone()
    print('=== FINGRID-DIAGNOSTIIKKA v0.6.1 ===')
    if not row:
        print('Fingrid-ajoa ei loydy tietokannasta.')
        raise SystemExit(2)
    run_id,issue=row
    print('Viimeisin Fingrid-ajo:',issue,run_id)
    print()
    for did,name,metric in [(166,'Kulutusennuste 72 h','consumption_forecast_mw'),(245,'Tuulivoimaennuste 72 h','wind_forecast_mw')]:
        log=c.execute('SELECT fetched_rows,status,message FROM ingestion_log WHERE run_id=? AND dataset_id=? ORDER BY id DESC LIMIT 1',(run_id,did)).fetchone()
        n=c.execute('SELECT COUNT(*) FROM forecasts WHERE run_id=? AND dataset_id=?',(run_id,did)).fetchone()[0]
        lohi=c.execute('SELECT MIN(valid_time),MAX(valid_time) FROM forecasts WHERE run_id=? AND dataset_id=?',(run_id,did)).fetchone()
        print(f'Dataset {did} - {name}')
        if log:
            print('  ingestion_log:', 'status='+str(log[1]), 'haettu='+str(log[0]))
            if log[2]: print('  viesti:',log[2])
        else:
            print('  ingestion_log: EI MERKINTAA')
        print('  tietokannassa:',n,'rivia')
        if lohi and lohi[0]: print('  aikavali:',lohi[0],'->',lohi[1])
        print()
    print('Jos molemmissa tietokannassa on riveja, v0.6:n nollat johtuivat source-valintavirheesta ja v0.6.1 korjaa sen.')
