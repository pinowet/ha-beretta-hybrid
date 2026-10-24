# Mappa registri del bus RS485 Beretta ibrido

Ricavata da catture passive del bus (20/10/2026) confrontate con le pagine INFO del
Hi,Comfort T300. Bus: Modbus RTU, 9600 8N1. **Unico master: il T300**, ciclo ogni ~3,4 s.

| Slave | Dispositivo |
|---|---|
| 1 | Pompa di calore Hydro Unit M (mappa Midea M-Thermal) |
| 100 | Caldaia Mynute X |

## PdC – slave 1, holding register (letti dal T300 con FC3)

| Reg | Grandezza | Scala / note |
|---|---|---|
| 0 | Accensione | 0 = spenta, 2 = zona 1 accesa (scritto dal T300) |
| 1 | Modo impostato | 1 auto, 2 raffrescamento, 3 riscaldamento |
| 2 | Setpoint acqua | byte basso zona 1, byte alto zona 2, °C (scritto dal T300) |
| 5 | ? | sempre 0 |
| 100 | Frequenza compressore | Hz |
| 101 | Stato di funzionamento | 0 ferma, 2 raffrescamento, 3 riscaldamento, 5 sanitario |
| 104 | Temperatura ritorno acqua | °C |
| 105 | Temperatura mandata acqua | °C |
| 107 | Temperatura esterna | °C, con segno |
| 108 | Refrigerante tubo alta pressione | °C |
| 109 | Refrigerante tubo bassa pressione | °C |
| 112 | Refrigerante scambiatore | °C |
| 113 | Refrigerante condensatore | °C |
| 122 | Ore compressore | h |
| 123 | Taglia | kW (8) |
| 124 | Codice errore | 0 = nessuno |
| 125–127 | ? | sempre 0 |
| 128 | Stato a bit (status bit 1 Midea) | 0x0400 fisso = bit 10 sorgente ausiliaria (caldaia); impulsi 0x2400 = bit 13 sbrinamento (da confermare); bit 14 antigelo, bit 15 ritorno olio |
| 129 | Stato a bit | 0x20 / 0x68 / 0x2068 con circolatore e compressore attivi |
| 138 | Portata acqua | ×0,01 m³/h |
| 140 | Potenza termica resa | ×0,01 kW |
| 143–144 | Energia consumata | kWh, 32 bit (alto/basso) |
| 210, 232, 272 | Parametri | 25217, −10, 34 (fissi) |

Sequenza osservata alla richiesta di calore: scrittura reg 0 = 2 e reg 2 = 48/48 °C →
circolatore dopo ~90 s → compressore dopo ~4 min. Allo spegnimento post-circolazione ~2 min.

## Caldaia – slave 100

### Input register (letti con FC4, 1000–1017)

| Reg | Grandezza | Scala / note |
|---|---|---|
| 1003 | Pressione impianto | ×0,1 bar |
| 1006 | Temperatura mandata | ×0,1 °C |
| 1007 | Temperatura ritorno | ×0,1 °C |
| 1008 | Temperatura sanitario | ×0,1 °C |
| 1009 | Temperatura fumi | ×0,1 °C |
| 1010 | Sonda esterna | ×0,1 °C, −40,0 = non collegata |
| 1012 | Ventilatore, giri richiesti | rpm (accensione 5500, max 7600) |
| 1013 | Ventilatore, giri reali | rpm |
| 1014 | Stato a bit | 0x100 riposo; bit 1 (0x002) sanitario; bit 9 (0x200) richiesta; bit 3 (0x008) fiamma |
| 1016 | Stato a bit | 0x50A6 riposo, bit 7 azzerato durante il sanitario |
| 1000–1002, 1004–1005, 1011, 1015, 1017 | ? | fissi |

### Holding register scritti dal T300 (FC16, 2000–2019, a ogni ciclo)

| Reg | Grandezza | Scala / note |
|---|---|---|
| 2000 | Parola di comando | 0x70B2 riposo; bit 2 (0x004) sanitario; bit 10 (0x400) richiesta riscaldamento |
| 2002 | Setpoint sanitario | ×0,1 °C (verificato 50 → 54 → 50) |
| 2006 | ? | 0x2000 |
| 2017 | ? | 200 |

### Blocco parametri (3000–3079)

Scritto dal T300 con FC16 e riletto con FC3 **solo quando si modificano le impostazioni**.
Valori riconosciuti: 3012 = 1600 (giri minimi?), 3013 = 7600 (giri massimi),
3014 = 5500 (giri di accensione).

## Non presenti sul bus

Temperatura e setpoint ambiente, setpoint raffrescamento (in inverno), potenza elettrica
della PdC: gestiti internamente dal T300.
