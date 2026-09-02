from _bootstrap import *
from electricity_forecaster.weather_ingest import ingest_weather
if __name__=='__main__':
    run,n,msg=ingest_weather(); print('Weather run:',run,'rows:',n)
    if msg: print('Huomiot:'); [print(' -',x) for x in msg]
