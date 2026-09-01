"""Recall adaptér: experiment, který nesmí být na obtíž, když je vypnutý.

`docs/plans/tasks.md` Fáze 7. Tenhle soubor hlídá dvě různé věci a ta druhá je
důležitější než ta první. Za prvé, že adaptér dělá, co má. Za druhé — a to je
ten důvod, proč sem patří i testy vypnutého stavu — že **nesmí nic pokazit**:
běh se nezastaví, když démon neběží ani když klient není nainstalovaný, banka
se neuhodne, a adresa mimo tenhle stroj se odmítne dřív, než se z projektu
cokoli odešle.

Poslední test mluví s HTTP serverem přes skutečného klienta. Přeskočí se, když
`hindsight-client` nainstalovaný není — což je normální stav, protože je to
volitelná závislost.
"""

from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from agency import cli, ingest, metrics, proc, recall, runs
from agency.util import read_json, write_json


class FakeResult(SimpleNamespace):
    """To, co vrací klient — objekt s atributy, ne dict."""


class FakeClient:
    def __init__(self, results=None, boom=None):
        self.results, self.boom = results or [], boom
        self.recalled, self.retained = [], []

    def recall(self, **kw):
        if self.boom:
            raise self.boom
        self.recalled.append(kw)
        return SimpleNamespace(results=self.results)

    def retain(self, **kw):
        if self.boom:
            raise self.boom
        self.retained.append(kw)
        return SimpleNamespace(success=True)


def hit(text="Reconsent flow je pro tenhle web irelevantní", tags=None, **over):
    return FakeResult(id="m1", text=text, type="world", context=None,
                      document_id=None, tags=tags or [], mentioned_at=None, **over)


@pytest.fixture
def client(monkeypatch):
    """Klient, kterého adaptér dostane. Test si vybírá, co odpoví."""
    made = FakeClient()
    monkeypatch.setattr(recall, "_client", lambda url: made)
    # Adaptér nesmí sáhnout na skutečné `~/.hindsight/coding-agent.json`.
    monkeypatch.setattr(recall, "hindsight_config", dict)
    return made


def enable(project, pack="review-graph", **over):
    """Pack s zapnutým recallem — najatý, ne jen nakonfigurovaný: doctor se
    ptá instalace, ne adresáře."""
    cfg = project.pack_config(pack) or {}
    cfg["recall"] = {"enabled": True, **over}
    write_json(project.agency_dir / f"{pack}.json", cfg)
    state = project.installed()
    state.setdefault("packs", {})[pack] = {"version": "0.1.0", "ref": f"{pack}@0.1.0"}
    project.save_installed(state)
    return cfg


# ------------------------------------------------------------------ vypnuto

def test_vypnuty_adapter_nesaha_nikam(project, make_run, monkeypatch):
    """Výchozí stav. Kdyby vypnutý adaptér otevřel spojení nebo napsal soubor,
    byl by to experiment, o který nikdo nepožádal."""
    monkeypatch.setattr(recall, "_client", lambda url: pytest.fail("nesmí se volat"))
    run = make_run()

    got = recall.for_run(project, run, project.pack_config("review-graph") or {})

    assert got == {"enabled": False}
    assert not (run.dir / "evidence" / "recall.json").exists()


def test_chybejici_klient_beh_nezastavi(project, make_run, monkeypatch):
    """`hindsight-client` je volitelná závislost. Zapnutý flag bez ní je chyba
    konfigurace, ne důvod, proč nemá proběhnout recenze."""
    monkeypatch.setattr(recall, "hindsight_config", dict)
    def missing(url):
        raise ImportError("No module named 'hindsight_client'")
    monkeypatch.setattr(recall, "_client", missing)
    cfg = enable(project)
    run = make_run()

    got = recall.for_run(project, run, cfg)

    assert got["enabled"] and "not installed" in got["error"]
    assert "results" not in got


def test_neni_li_demon_beh_pokracuje(project, make_run, monkeypatch, client):
    """Démon, který neběží, je běžný stav — plugin ho startuje na pozadí a
    první session po restartu ho nezastihne."""
    client.boom = ConnectionRefusedError("nikdo neposlouchá")
    cfg = enable(project)
    run = make_run()

    got = recall.for_run(project, run, cfg)

    assert "ConnectionRefusedError" in got["error"]


# ------------------------------------------------------------------ hranice

def test_nelokalni_adresa_se_odmita(project, make_run, monkeypatch):
    """Konfigurace harnessu má výchozí režim `cloud`. Poslat podle ní nálezy
    projektu do cizí služby by bylo přesně to, co má tenhle nástroj zakázané —
    a mlčky by to nikdo nepoznal."""
    monkeypatch.setattr(recall, "_client", lambda url: pytest.fail("nesmí se volat"))
    monkeypatch.setattr(recall, "hindsight_config", dict)
    cfg = enable(project, baseUrl="https://api.hindsight.example.com")
    run = make_run()

    got = recall.for_run(project, run, cfg)

    assert "not on this machine" in got["error"]
    assert "results" not in got


def test_adresa_se_bere_z_konfigurace_harnessu(project, monkeypatch):
    """Kdyby si adaptér adresu vymýšlel sám, uživatel s démonem na jiném portu
    by dostal prázdnou banku a žádné vysvětlení."""
    monkeypatch.delenv("HINDSIGHT_API_URL", raising=False)
    monkeypatch.delenv("HINDSIGHT_API_PORT", raising=False)
    monkeypatch.setattr(recall, "hindsight_config", lambda: {"apiPort": 9999})

    assert recall.endpoint({}) == {"url": "http://127.0.0.1:9999",
                                   "source": "~/.hindsight/coding-agent.json"}

    monkeypatch.setattr(recall, "hindsight_config", dict)
    assert recall.endpoint({})["url"] == f"http://127.0.0.1:{recall.DEFAULT_PORT}"


def test_banka_je_hlavni_worktree_ne_ten_odlozeny(project):
    """Recenzent běží v jednorázovém worktree. Kdyby se banka jmenovala podle
    něj, měl by každý běh vlastní paměť — a sdílení s interaktivní session,
    kvůli kterému celý adaptér existuje, by nefungovalo."""
    wt = project.root.parent / "wt-pr-12"
    subprocess.run(["git", "worktree", "add", "-q", "--detach", str(wt)],
                   cwd=project.root, check=True, capture_output=True)

    assert recall.bank_id(project) == f"coding-agent::{project.root.name}"
    assert recall.bank_id(SimpleNamespace(root=wt)) == recall.bank_id(project)


def test_bez_gitu_se_banka_nehada(tmp_path):
    """Uhodnutá banka je horší než žádná: nikdo jiný by ji nenašel a paměť by
    se tiše rozdvojila. Plugin z téhož důvodu radši selže."""
    (tmp_path / "neni-repo").mkdir()

    assert recall.bank_id(SimpleNamespace(root=tmp_path / "neni-repo")) is None


# ------------------------------------------------------------------ recall

def test_zeptal_jsem_se_a_nic_tam_nebylo_je_taky_zaznam(project, make_run, client):
    """Prázdný výsledek a vypnutý adaptér jsou dvě různá tvrzení. Po deseti
    bězích se budou rozlišovat, takže soubor musí vzniknout i prázdný."""
    cfg = enable(project)
    run = make_run()

    recall.for_run(project, run, cfg, brief={"focus": "VOP pro nový web"})

    written = read_json(run.dir / "evidence" / "recall.json")
    assert written["results"] == [] and written["foreign"] == 0
    assert "VOP pro nový web" in written["query"]
    assert client.recalled[0]["bank_id"] == recall.bank_id(project)


def test_cizi_zasahy_jsou_cele_kill_criterion(project, make_run, client):
    """Co uložila Agency, měl bundle taky. Číslo, které rozhoduje o osudu
    adaptéru, je počet zásahů, které odjinud — z interaktivní session, z jiného
    harnessu."""
    client.results = [hit(tags=[recall.TAG, "pack:legal"]), hit(tags=["claude-code"]), hit()]
    cfg = enable(project)
    run = make_run()

    got = recall.for_run(project, run, cfg)

    assert len(got["results"]) == 3
    assert got["foreign"] == 2, "vlastní zásah se nepočítá"


def test_pamet_o_recallu_nepatri_do_grafu(project):
    """Táž past jako u `knownFindings` ve Fázi 0: `run.graph` má v `run.v1`
    zavřený seznam klíčů, takže cokoli navíc z běhu dělá neplatný záznam."""
    for key in ("recalled", "recalledForeign", "recallError"):
        assert key in runs.MEMORY_STATS


# ------------------------------------------------------------------ retain

def test_bez_shrnuti_se_neuklada_nic(project, make_run, client):
    """Ukládá se `summary.md` — jediný text, kde specialista mluví vlastními
    slovy. Běh, který ho nenapsal, nemá co poslat."""
    cfg = enable(project)
    run = make_run()

    got = recall.after_ingest(project, run, cfg)

    assert got["skipped"] == "the run left no summary.md"
    assert client.retained == []


def test_uklada_se_rozhodnuti_ne_tvrzeni(project, make_run, client):
    """Kandidát je tvrzení, o kterém nikdo nerozhodl. Banka plná takových by
    recall utopila — a zamítnutí je přitom to nejcennější, co projekt ví."""
    cfg = enable(project)
    run = make_run()
    finding = run.findings()[0]
    event = {"state": "rejected", "reason": "out-of-scope", "note": "web nemá účty",
             "by": "hire:po@claude"}

    recall.after_decision(project, run, cfg, finding, event)

    sent = client.retained[0]
    assert sent["document_id"] == f"agency:finding:{finding['id']}"
    assert "Rejected (out-of-scope)" in sent["content"] and "web nemá účty" in sent["content"]
    assert recall.TAG in sent["tags"] and "decision:rejected" in sent["tags"]


def test_ingest_ulozi_shrnuti_bez_druheho_prikazu(project, make_run, client):
    """Brána je jediné místo, kterým projde `agency ingest` i `run --wait`."""
    enable(project)
    run = make_run()
    (run.dir / "summary.md").write_text("# Shrnutí\n\nProšel jsem VOP.\n", encoding="utf-8")

    result = ingest.ingest(project, run)

    assert result["recall"]["retained"] == f"agency:run:{run.id}"
    assert "Prošel jsem VOP" in client.retained[0]["content"]


# ------------------------------------------------------------------ vyhodnocení

def test_metriky_umi_kill_criterion_spocitat(project, make_run):
    """Po deseti bězích se má dát odpovědět číslem, ne dojmem."""
    make_run(run_id="01AAAAAAAAAAAAAAAAAAAAAAAA",
             evidence={"recalled": 4, "recalledForeign": 0})
    make_run(run_id="01BBBBBBBBBBBBBBBBBBBBBBBB",
             evidence={"recalled": 0, "recallError": "ConnectionRefusedError"})

    got = metrics.collect(project)["recall"]

    assert got == {"runs": 2, "hits": 4, "foreign": 0, "errors": 1}


def test_doctor_mlci_dokud_si_recall_nikdo_nezapne(project):
    """Řádek „vypnuto" u experimentu, o který nikdo nepožádal, je šum."""
    assert cli._recall_states(project) == []


def test_doctor_rekne_ze_demon_neni(project, monkeypatch, capsys):
    """Doctor kontroluje předpoklady PŘED během. Nedostupný démon není chyba
    běhu, ale je to důvod, proč z recallu nic nepřijde — a to se má vědět
    dřív, než se spálí sezení."""
    monkeypatch.setattr(recall, "hindsight_config", dict)
    # Port 1, ne výchozí 9077: test nesmí záviset na tom, jestli si na tomhle
    # stroji zrovna někdo démona nepustil.
    enable(project, baseUrl="http://127.0.0.1:1")

    cli.cmd_doctor(SimpleNamespace(repo=str(project.root), json=False))
    printed = capsys.readouterr().out

    assert "recall review-graph" in printed
    assert "no daemon at" in printed and "runs continue without it" in printed


# ------------------------------------------------------------------ po drátě

class Stub(BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):  # noqa: N802 — jméno předepisuje BaseHTTPRequestHandler
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"] or 0)) or b"{}")
        Stub.seen.append((self.path, body))
        if self.path.endswith("/memories/recall"):
            answer = {"results": [{"id": "m1", "text": "Účty letos nebudou.",
                                   "tags": ["claude-code"]}]}
        else:
            answer = {"success": True, "bank_id": "b", "items_count": 1, "async": False}
        raw = json.dumps(answer).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


def test_po_dratě_se_skutecnym_klientem(project, make_run, monkeypatch):
    """Jediné místo, kde se ověří, že to, co adaptér posílá, opravdu projde
    knihovnou ven — a že se odpověď dá přečíst zpátky. Zbytek testů si klienta
    podstrkuje, takže o formátu drátu netvrdí nic."""
    pytest.importorskip("hindsight_client",
                        reason="volitelná závislost — `uv pip install hindsight-client`")
    Stub.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(recall, "hindsight_config", dict)
    cfg = enable(project, baseUrl=f"http://127.0.0.1:{server.server_port}")
    run = make_run()

    try:
        got = recall.for_run(project, run, cfg, brief={"focus": "monetizace"})
    finally:
        server.shutdown()

    assert "error" not in got, got.get("error")
    assert got["results"][0]["text"] == "Účty letos nebudou."
    assert got["foreign"] == 1
    path, body = Stub.seen[0]
    assert path.endswith(f"/banks/{recall.bank_id(project)}/memories/recall")
    assert body["query"].startswith("monetizace")


def test_port_open_rekne_jen_to_co_overil():
    """Doctor se ptá „je tam démon". TCP odpověď na víc nestačí a tvrdit víc
    by znamenalo poslat uživatele hledat chybu, která není."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert proc.port_open(f"http://127.0.0.1:{server.server_port}") == (True, "")
    finally:
        server.shutdown()
    ok, why = proc.port_open("http://127.0.0.1:1")
    assert not ok and "nothing listens" in why
