# v1.5.8 Fast Dual-Origin Build

v1.5.7 ei välttämättä ollut jumissa, mutta se rakensi lähes miljoona
harjoitusriviä Python-silmukoilla ja laski samat rolling-statistiikat uudelleen
tuhansia kertoja. Tämän vuoksi ruudulle ei tullut pitkään aikaan mitään ja
muistinkäyttö saattoi kasvaa huomattavasti.

v1.5.8 korvaa vain historiallisen horizon-builderin tehokkaammalla versiolla.

## Korvaa

```text
historical_v15\asof.py
```

## Lisää

```text
build_horizon_v1_5_8.py
```

## Ajo

Jos v1.5.7 on edelleen käynnissä, keskeytä se:

```text
Ctrl+C
```

Aja sen jälkeen:

```powershell
.\.venv\Scripts\python.exe build_horizon_v1_5_8.py
```

Nyt näet etenemisen:

```text
prepared issue origins: ...
group 01/22: issue 06:15 D+2
group 02/22: issue 06:15 D+3
...
group 22/22: issue 16:15 D+12
assembled horizon rows: ...
writing parquet ...
DONE
```

Tulos:

```text
data\processed\v1_5_8\horizon_asof_dual_d2_d12.parquet
```

Huom: tuotannon kahden ajon Scheduled Task -muutos v1.5.7-paketissa
säilyy ennallaan. Tämä hotfix koskee vain historiallisen ML-aineiston
rakentamisen nopeutta.
