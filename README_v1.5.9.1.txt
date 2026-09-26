v1.5.9.1 HOTFIX

Korvaa vain:
  36_AJA_JA_ARKISTOI.bat

Syy:
v1.5.9 käytti --root "%~dp0". Windowsissa %~dp0 päättyy
kenoviivaan. Kun kenoviiva on juuri ennen sulkevaa lainausmerkkiä,
Pythonin komentoriviparsinta voi tulkita argumentin väärin ja palauttaa
exit-koodin 2.

Korjaus:
wrapper siirtyy ensin projektihakemistoon ja käyttää sen jälkeen %CD%:tä,
joka ei pääty kenoviivaan.

Testi:
  .\36_AJA_JA_ARKISTOI.bat afternoon

Onnistumisen lopussa:
  [OK] Ennustesnapshot tallennettu.
  [OK] Tuotantoajo ja snapshot valmis.
