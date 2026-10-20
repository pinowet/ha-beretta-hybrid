# Beretta Ibrido – Modbus passivo per Home Assistant

Integrazione custom per leggere in **Home Assistant** i dati di un impianto ibrido Beretta
(pompa di calore **Hydro Unit M** + caldaia **Mynute X**) gestito dal termostato
**Hi,Comfort T300**, ascoltando il bus RS485 tramite un gateway **Waveshare RS485 TO ETH**.

> ⚠️ Progetto non ufficiale, non affiliato a Beretta. Uso a proprio rischio.

## Come funziona

Nel sistema ibrido il **T300 è l'unico master Modbus**: interroga la PdC (slave 1) e la
caldaia (slave 100) e invia loro i comandi. L'integrazione **ascolta soltanto** il traffico
tra T300, PdC e caldaia e lo decodifica:

- **non trasmette mai nulla sul bus**: la connessione TCP verso il gateway è in sola
  ricezione, quindi il T300 resta l'unico master e la logica ibrida non viene alterata;
- vede **solo i registri che il T300 interroga o scrive** (vedi [mappa registri](docs/registri.md)).

## Requisiti hardware

- Gateway Waveshare **RS485 TO ETH (B)** (o equivalente in modalità trasparente)
- Collegamento in parallelo sul bus Beretta: **A → A**, **B → B**.
  **Non collegare il + del bus.** Nessuna resistenza di terminazione aggiuntiva.
- GND del gateway al **−** del bus: di solito non necessario con un alimentatore a spina
  flottante. Consigliato se l'alimentatore del gateway è collegato a terra oppure se nella
  diagnostica crescono `bytes_discarded` / `unmatched_responses`.

Configurazione del gateway (VirCom o pagina web):

| Parametro | Valore |
|---|---|
| Work Mode | TCP Server |
| Port | 4196 |
| Transfer Protocol | **None** (trasparente). Non usare la modalità Modbus gateway |
| Seriale | 9600, 8, None, 1 |
| RS485 Multi-Host | disattivato |

## Installazione (HACS)

1. HACS → menu ⋮ → **Repository personalizzati**
2. Repository: `https://github.com/pinowet/ha-beretta-hybrid`, tipo **Integrazione**
3. Cerca **Beretta Ibrido**, **Scarica**, riavvia Home Assistant
4. Impostazioni → Dispositivi e servizi → **Aggiungi integrazione** → *Beretta Ibrido*
5. Inserisci IP e porta del gateway (porta predefinita 4196)

## Entità

**Pompa di calore**: accesa, compressore, circolazione, errore, modo impostato, stato,
setpoint acqua, frequenza compressore, temperature mandata/ritorno/esterna, temperature
refrigerante, portata, potenza termica resa, energia consumata, ore compressore, codice errore.

**Caldaia**: fiamma, sanitario in corso, pressione, temperature mandata/ritorno/sanitario/fumi,
velocità ventilatore, setpoint sanitario.

**Hi,Comfort T300**: richiesta riscaldamento, richiesta sanitario, stato del bus RS485,
ultimo aggiornamento parametri.

Alcune entità diagnostiche (registri di stato grezzi, sonda esterna caldaia, setpoint zona 2)
sono disabilitate di default.

## Opzioni

**Intervallo minimo di aggiornamento** (predefinito 30 s): limita la frequenza con cui i valori
che cambiano spesso (frequenza, potenza, portata, ventilatore, temperature caldaia) vengono
scritti nel database. Gli stati on/off e i valori lenti sono aggiornati subito.

## Strumenti

`tools/sniffer_beretta.py`: script stand-alone (solo Python) per catturare e analizzare il
traffico del bus da PC, utile per scoprire nuovi registri:

```
python tools/sniffer_beretta.py 192.168.1.200 --durata 30
```

La diagnostica dell'integrazione (Dispositivi e servizi → Beretta Ibrido → ⋮ → Scarica
diagnostica) contiene la tabella completa dei registri visti sul bus.
