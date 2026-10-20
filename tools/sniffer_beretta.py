#!/usr/bin/env python3
"""
sniffer_beretta.py
Ascolto PASSIVO del bus RS485 (Modbus RTU) dell'impianto ibrido Beretta
(T300 master, caldaia Mynute X e PdC Hydro Unit M slave) tramite
Waveshare RS485 TO ETH (B) in modalita' trasparente (TCP Server).

SOLO LETTURA: lo script non invia MAI byte al Waveshare, quindi il Waveshare
non trasmette nulla sul bus e il T300 resta l'unico master.

Uso:
    python sniffer_beretta.py 192.168.1.200
    python sniffer_beretta.py 192.168.1.200 --porta 4196 --durata 30
    python sniffer_beretta.py --rianalizza cattura_XXXX/grezzo.log

Requisiti: Python 3.8+ (nessuna libreria esterna).
"""
import argparse
import csv
import datetime as dt
import os
import socket
import sys
import time

TABELLE = {1: "coil", 2: "ingresso_discreto", 3: "holding", 4: "input"}


# ----------------------------------------------------------------- utilita'
def crc16(data) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def crc_ok(frame) -> bool:
    if len(frame) < 4:
        return False
    c = crc16(frame[:-2])
    return frame[-2] == (c & 0xFF) and frame[-1] == (c >> 8)


def s16(v: int) -> int:
    return v - 65536 if v >= 32768 else v


def ora_txt(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


# -------------------------------------------------------------- analizzatore
class Analizzatore:
    def __init__(self, cartella: str):
        self.cartella = cartella
        self.buf = bytearray()
        self.pending = None  # (slave, fc, start, count, frame)
        self.byte_tot = 0
        self.frame_tot = 0
        self.scartati = 0
        self.orfani = 0
        self.eccezioni = 0
        self.slave = {}
        self.registri = {}
        self.polling = {}

        self.f_frame = open(os.path.join(cartella, "frame.csv"), "w", newline="", encoding="utf-8")
        self.w_frame = csv.writer(self.f_frame, delimiter=";")
        self.w_frame.writerow(["ora", "tipo", "slave", "funzione", "hex"])

        self.f_val = open(os.path.join(cartella, "valori.csv"), "w", newline="", encoding="utf-8")
        self.w_val = csv.writer(self.f_val, delimiter=";")
        self.w_val.writerow(["ora", "slave", "operazione", "tabella", "registro", "valore_u16", "valore_s16"])

    # -- ingresso dati
    def alimenta(self, dati: bytes, ts: float):
        self.byte_tot += len(dati)
        self.buf.extend(dati)
        usati = self._analizza(ts)
        if usati:
            del self.buf[:usati]

    def _candidati(self, i):
        """Possibili (tipo, lunghezza) del frame che inizia in i. Lunghezza None = servono altri byte."""
        buf = self.buf
        n = len(buf) - i
        addr, fc = buf[i], buf[i + 1]
        if addr > 247:
            return []
        c = []
        if fc in (1, 2, 3, 4):
            c.append(("richiesta", 8))
            c.append(("risposta", 5 + buf[i + 2]))
        elif fc in (5, 6):
            c.append(("scrittura", 8))
        elif fc in (15, 16):
            c.append(("conferma", 8))
            c.append(("scrittura", 9 + buf[i + 6] if n >= 7 else None))
        elif fc >= 0x80 and (fc & 0x7F) in (1, 2, 3, 4, 5, 6, 15, 16):
            c.append(("eccezione", 5))
        return c

    def _scegli(self, validi, i):
        if len(validi) == 1:
            return validi[0]
        tipi = dict(validi)
        addr, fc = self.buf[i], self.buf[i + 1]
        p = self.pending
        if p and p[0] == addr and p[1] == fc:
            for t in ("risposta", "conferma"):
                if t in tipi:
                    return t, tipi[t]
        return validi[0]

    def _analizza(self, ts):
        buf = self.buf
        L = len(buf)
        i = 0
        while L - i >= 4:
            validi, serve_altro = [], False
            for tipo, lung in self._candidati(i):
                if lung is None or i + lung > L:
                    serve_altro = True
                    continue
                if lung <= 256 and crc_ok(buf[i:i + lung]):
                    validi.append((tipo, lung))
            if validi:
                tipo, lung = self._scegli(validi, i)
                self._frame(tipo, bytes(buf[i:i + lung]), ts)
                i += lung
                continue
            if serve_altro and L - i < 300:
                break  # aspetta altri byte
            i += 1
            self.scartati += 1
        return i

    # -- interpretazione frame
    def _frame(self, tipo, f, ts):
        addr, fc = f[0], f[1]
        self.frame_tot += 1
        self.slave[addr] = self.slave.get(addr, 0) + 1
        if fc in (5, 6) and self.pending and self.pending[4] == f:
            tipo = "conferma"  # eco della scrittura singola
        self.w_frame.writerow([ora_txt(ts), tipo, addr, fc, f.hex(" ")])

        if tipo == "richiesta":
            start, count = (f[2] << 8) | f[3], (f[4] << 8) | f[5]
            self.pending = (addr, fc, start, count, f)
            k = (addr, fc, start, count)
            p = self.polling.get(k)
            if p:
                p[0] += 1
                p[2] = ts
            else:
                self.polling[k] = [1, ts, ts]

        elif tipo == "risposta":
            p = self.pending
            self.pending = None
            if not p or p[0] != addr or p[1] != fc:
                self.orfani += 1
                return
            start, count, nb = p[2], p[3], f[2]
            dati = f[3:3 + nb]
            if fc in (3, 4):
                if nb != 2 * count:
                    self.orfani += 1
                    return
                for k in range(count):
                    self._registra(ts, addr, "lettura", fc, start + k, (dati[2 * k] << 8) | dati[2 * k + 1])
            else:
                for k in range(count):
                    bit = (dati[k // 8] >> (k % 8)) & 1 if k // 8 < nb else 0
                    self._registra(ts, addr, "lettura", fc, start + k, bit)

        elif tipo == "scrittura":
            if fc == 6:
                self._registra(ts, addr, "scrittura", 3, (f[2] << 8) | f[3], (f[4] << 8) | f[5])
            elif fc == 5:
                self._registra(ts, addr, "scrittura", 1, (f[2] << 8) | f[3], 1 if f[4] == 0xFF else 0)
            elif fc == 16:
                start, count = (f[2] << 8) | f[3], (f[4] << 8) | f[5]
                for k in range(count):
                    self._registra(ts, addr, "scrittura", 3, start + k, (f[7 + 2 * k] << 8) | f[8 + 2 * k])
            elif fc == 15:
                start, count = (f[2] << 8) | f[3], (f[4] << 8) | f[5]
                dati = f[7:7 + f[6]]
                for k in range(count):
                    self._registra(ts, addr, "scrittura", 1, start + k, (dati[k // 8] >> (k % 8)) & 1)
            self.pending = (addr, fc, 0, 0, f)

        elif tipo == "conferma":
            self.pending = None

        elif tipo == "eccezione":
            self.eccezioni += 1
            self.pending = None

    def _registra(self, ts, addr, op, fc, reg, v):
        self.w_val.writerow([ora_txt(ts), addr, op, TABELLE[fc], reg, v, s16(v)])
        k = (addr, op, fc, reg)
        r = self.registri.get(k)
        sv = s16(v)
        if r is None:
            self.registri[k] = {"n": 1, "primo": v, "ultimo": v, "min": sv, "max": sv, "cambi": 0, "distinti": [v]}
            return
        r["n"] += 1
        if v != r["ultimo"]:
            r["cambi"] += 1
        r["ultimo"] = v
        r["min"] = min(r["min"], sv)
        r["max"] = max(r["max"], sv)
        if v not in r["distinti"] and len(r["distinti"]) < 15:
            r["distinti"].append(v)

    # -- diagnostica e riepilogo
    def diagnosi(self) -> str:
        if self.byte_tot == 0:
            return "nessun byte: controlla IP/porta del Waveshare e il collegamento A/B"
        perc = self.scartati * 100 / self.byte_tot
        if self.frame_tot == 0 and self.byte_tot > 200:
            return "byte senza frame validi: baud/parita' errati o A/B invertiti"
        if perc > 30:
            return f"{perc:.0f}% byte scartati: verifica baud/parita'"
        return "OK"

    def stato(self):
        sl = ", ".join(f"{a}:{n}" for a, n in sorted(self.slave.items())) or "-"
        print(f"[{ora_txt(time.time())[11:19]}] byte {self.byte_tot}  frame {self.frame_tot}  "
              f"scartati {self.scartati}  slave {{{sl}}}  -> {self.diagnosi()}", flush=True)

    def salva_riepilogo(self):
        self.f_frame.flush()
        self.f_val.flush()
        righe = [
            f"Riepilogo cattura - {ora_txt(time.time())}",
            f"Byte ricevuti: {self.byte_tot}   Frame validi: {self.frame_tot}   "
            f"Byte scartati: {self.scartati}   Risposte senza richiesta: {self.orfani}   Eccezioni: {self.eccezioni}",
            f"Diagnosi: {self.diagnosi()}",
            "",
            "SLAVE VISTI (indirizzo: frame)",
        ]
        righe += [f"  {a}: {n}" for a, n in sorted(self.slave.items())]
        righe += ["", "INTERROGAZIONI DEL MASTER (slave, tabella, registri, volte, intervallo medio)"]
        for (a, fc, st, cnt), (n, t0, t1) in sorted(self.polling.items()):
            inter = f"{(t1 - t0) / (n - 1):.1f} s" if n > 1 else "-"
            righe.append(f"  slave {a:3}  {TABELLE.get(fc, fc):18} {st:5}..{st + cnt - 1:<5}  {n:5} volte  ogni {inter}")
        righe += ["", "REGISTRI (slave, operazione, tabella, registro: n, ultimo u16/s16, min..max s16, cambi, valori)"]
        for (a, op, fc, reg), r in sorted(self.registri.items()):
            righe.append(
                f"  slave {a:3}  {op:9} {TABELLE[fc]:18} {reg:5}: n={r['n']:<5} ultimo={r['ultimo']}/{s16(r['ultimo'])}  "
                f"{r['min']}..{r['max']}  cambi={r['cambi']}  valori={r['distinti']}")
        with open(os.path.join(self.cartella, "riepilogo.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(righe) + "\n")

        with open(os.path.join(self.cartella, "riepilogo_registri.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["slave", "operazione", "tabella", "registro", "letture", "primo", "ultimo_u16",
                        "ultimo_s16", "min_s16", "max_s16", "cambi", "valori_distinti"])
            for (a, op, fc, reg), r in sorted(self.registri.items()):
                w.writerow([a, op, TABELLE[fc], reg, r["n"], r["primo"], r["ultimo"], s16(r["ultimo"]),
                            r["min"], r["max"], r["cambi"], " ".join(map(str, r["distinti"]))])

    def chiudi(self):
        self.salva_riepilogo()
        self.f_frame.close()
        self.f_val.close()


# ------------------------------------------------------------------- cattura
def cattura(args, an, grezzo):
    fine = time.time() + args.durata * 60 if args.durata > 0 else None
    t_stato = t_salva = time.time()
    while True:
        try:
            print(f"Connessione a {args.host}:{args.porta} ...", flush=True)
            with socket.create_connection((args.host, args.porta), timeout=10) as s:
                s.settimeout(1.0)
                print("Connesso. In ascolto (Ctrl+C per terminare). Nessun dato viene inviato sul bus.", flush=True)
                while True:
                    try:
                        dati = s.recv(4096)  # SOLO ricezione: nessuna send() in tutto lo script
                    except TimeoutError:
                        dati = None
                    ora = time.time()
                    if dati == b"":
                        print("Connessione chiusa dal Waveshare.", flush=True)
                        break
                    if dati:
                        grezzo.write(f"{ora:.3f}\t{dati.hex(' ')}\n")
                        an.alimenta(dati, ora)
                    if ora - t_stato >= 10:
                        an.stato()
                        t_stato = ora
                    if ora - t_salva >= 60:
                        an.salva_riepilogo()
                        grezzo.flush()
                        t_salva = ora
                    if fine and ora >= fine:
                        return
        except OSError as e:
            print(f"Errore di connessione: {e}", flush=True)
        if fine and time.time() >= fine:
            return
        print("Nuovo tentativo tra 5 s ...", flush=True)
        time.sleep(5)


def rianalizza(percorso, an):
    with open(percorso, encoding="utf-8") as f:
        for riga in f:
            riga = riga.strip()
            if not riga:
                continue
            ts, hx = riga.split("\t", 1)
            an.alimenta(bytes.fromhex(hx), float(ts))


def main():
    ap = argparse.ArgumentParser(description="Ascolto passivo bus RS485 Beretta via Waveshare (solo lettura)")
    ap.add_argument("host", nargs="?", help="IP del Waveshare RS485 TO ETH (B)")
    ap.add_argument("--porta", type=int, default=4196, help="porta TCP del Waveshare (default 4196)")
    ap.add_argument("--durata", type=float, default=0, help="minuti di cattura (0 = fino a Ctrl+C)")
    ap.add_argument("--rianalizza", help="rianalizza un grezzo.log gia' registrato, senza collegarsi")
    args = ap.parse_args()
    if not args.host and not args.rianalizza:
        ap.error("indica l'IP del Waveshare oppure --rianalizza <file>")

    cartella = "cattura_" + dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.rianalizza:
        cartella += "_rianalisi"
    os.makedirs(cartella, exist_ok=True)
    an = Analizzatore(cartella)
    print(f"File in: {os.path.abspath(cartella)}")

    try:
        if args.rianalizza:
            rianalizza(args.rianalizza, an)
        else:
            with open(os.path.join(cartella, "grezzo.log"), "w", encoding="utf-8") as grezzo:
                cattura(args, an, grezzo)
    except KeyboardInterrupt:
        print("\nInterrotto.")
    finally:
        an.chiudi()
        an.stato()
        print(f"Riepilogo salvato in {os.path.join(cartella, 'riepilogo.txt')}")


if __name__ == "__main__":
    sys.exit(main())
