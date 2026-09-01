"""Třetí pack — a tím pádem zkouška, jestli formát unese i specialistu, který
nečte kód, ale dokumenty.

Recenzent a QA mají oba jeden zdroj pravdy: repozitář. Právník má dva — repozitář
a předpis, který v repozitáři není. Testy tady hlídají právě ty dva švy: že se
běhová politika bere z manifestu a ne z jména packu, a že nález, jehož evidence
je citace paragrafu a jehož kotva vede do markdownu, projde toutéž bránou jako
nález z grafu.

Nejdůležitější test v souboru je `test_aplikacni_brana_je_povinna_konfigurace`.
Pack, který neví, kdo je zákazník a jak je firma velká, umí vyrobit povinnost,
kterou nikdo nemá — a to je u tohohle specialisty ta nejdražší chyba.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agency import cli, config as agency_config, ingest, packs
from agency.util import write_json

from conftest import git, make_finding


# ------------------------------------------------------------ běhová politika

def test_politika_behu_je_v_manifestu_ne_v_kodu():
    legal = packs.load("legal")

    assert legal.run_policy["target"] == "workspace"
    assert legal.run_policy["worktree"] is False
    assert legal.run_policy["graph"] is False
    # Zadání bere, ale nevyžaduje: běh bez otázky je plnohodnotná revize
    # dokumentů, na rozdíl od QA, které bez zadání neví, co zkoušet.
    assert legal.run_policy["prompt"]["accepts"] is True
    assert legal.run_policy["prompt"]["required"] is False
    assert legal.skill_name == "agency-legal"


def test_napoveda_k_spusteni_se_odvozuje_z_manifestu():
    """Doctor napevno jmenoval dva packy. Třetí specialista by po něm zůstal
    neviditelný přesně ve chvíli, kdy ho uživatel hledá."""
    assert cli._run_hint(packs.load("review-graph")) == " --pr <n>"
    assert cli._run_hint(packs.load("qa")) == ' --prompt "…"'
    assert cli._run_hint(packs.load("legal")) == ""


# ------------------------------------------------------------------ instalace

def test_instalace_prinese_metodu_i_prameny(project):
    legal = packs.load("legal")

    packs.apply(legal, project, packs.plan(legal, project))

    skill = project.root / ".claude" / "skills" / "agency-legal"
    assert (skill / "SKILL.md").is_file()
    # Prameny nejsou příloha. Bez nich by pack citoval z paměti, což je přesně
    # ten způsob, jakým vznikají vymyšlené povinnosti.
    assert (skill / "references" / "sources.md").is_file()
    assert (skill / "references" / "cz-eu-baseline.md").is_file()


def test_aplikacni_brana_je_povinna_konfigurace(project):
    """`business.model` a `business.size` rozhodují, které režimy vůbec platí.
    Šablona je nechává prázdné schválně — doctor se na ně musí zeptat dřív,
    než pack vyrobí povinnost z cizího režimu."""
    legal = packs.load("legal")
    packs.apply(legal, project, packs.plan(legal, project))

    cfg = project.pack_config("legal") or {}
    assert cfg["business"]["model"] is None
    assert cfg["business"]["size"] is None
    assert set(legal.manifest["config"]["required"]) == {"business.model", "business.size"}

    # Dokud je gate prázdná, běh by měl podle doktora selhat.
    chybi = [k for k in legal.manifest["config"]["required"] if not cli._dig(cfg, k)]
    assert chybi == ["business.model", "business.size"]


def test_vychozi_dimenze_neobsahuji_marketplace(project):
    """Partneři a DAC7 se zapínají až tím, že projekt řekne, že má podnikatelské
    uživatele. Pustit je na e-shopu znamená hlásit povinnosti, které neplatí."""
    legal = packs.load("legal")
    packs.apply(legal, project, packs.plan(legal, project))

    cfg = project.pack_config("legal") or {}
    assert cfg["review"]["dimensions"] == ["terms", "consumer", "privacy", "over-compliance"]
    assert cfg["business"]["counterparties"]["businessUsers"] is False
    # Vyšší práh než u recenzenta: špatný právní nález mění produkt.
    assert cfg["review"]["minScore"] == 85
    assert cfg["posture"]["level"] == "proportionate"
    assert cfg["posture"]["requireCitation"] is True


def test_instalace_nepridava_dimenzi_kterou_pack_nezna(project):
    """Táž past jako u QA: detekce pravidel v projektu nesmí dopsat `repo-rules`
    packu, který takovou dimenzi nemá."""
    detected = {"slug": "o/r", "rules": "CLAUDE.md#rules", "docMap": None, "verifyCommand": None}

    legal = packs.load("legal")
    packs.apply(legal, project, packs.plan(legal, project), detected=detected)

    assert "repo-rules" not in (project.pack_config("legal") or {})["review"]["dimensions"]


def test_prameny_prava_jsou_v_konfiguraci_ne_v_metode(project):
    """Adresy pramenů patří projektu — jinak by se změna endpointu řešila
    upgradem packu a offline běh by nešel zapnout."""
    legal = packs.load("legal")
    packs.apply(legal, project, packs.plan(legal, project))

    src = (project.pack_config("legal") or {})["lawSources"]
    assert src["offline"] is False
    assert "eli" in src["esbirkaOpenData"]
    assert "celex" in src["cellar"]
    for host in ("e-sbirka.cz", "eur-lex.europa.eu", "uoou.gov.cz", "financnisprava.gov.cz"):
        assert host in src["allowedDomains"]


# -------------------------------------------------------------------- brána

def test_pravni_nalez_projde_toutez_branou(project, make_run):
    """`finding.v1` není přišitý na kód: nález, jehož kotva vede do markdownu
    a jehož evidence je citace předpisu, projde stejnou bránou i kotvou."""
    (project.root / "content").mkdir()
    vop = project.root / "content" / "vop.md"
    vop.write_text(
        "# Obchodní podmínky\n"
        "\n"
        "## 12. Změny podmínek\n"
        "Změny nabývají účinnosti dnem zveřejnění na webu.\n", encoding="utf-8")
    git(project.root, "add", "-A")
    git(project.root, "commit", "-q", "-m", "vop")

    commit = git(project.root, "rev-parse", "HEAD")
    run = make_run(findings=[], pack="legal@0.1.0",
                   target={"kind": "workspace", "ref": "main", "headRefOid": commit})
    f = make_finding(
        project, run.id,
        pack="legal@0.1.0",
        dimension="partners",
        severity="blocker",
        title="Změna podmínek pro partnery nemá 15denní lhůtu ani trvalý nosič",
        body=("Podle čl. 3 odst. 2 nařízení (EU) 2019/1150 musí být navržená změna "
              "oznámena na trvalém nosiči nejméně 15 dní předem; podle odst. 3 je "
              "změna provedená v rozporu s tím neplatná."),
        anchor={"file": "content/vop.md", "line": 4, "endLine": 4, "commit": commit,
                "snippet": "Změny nabývají účinnosti dnem zveřejnění na webu.",
                "symbol": None, "body": None},
        evidence=[{"kind": "doc",
                   "detail": "čl. 3 odst. 2 a 3 nařízení (EU) 2019/1150",
                   "source": "https://eur-lex.europa.eu/legal-content/CS/TXT/?uri=CELEX:32019R1150"}],
        score=96)
    write_json(run.findings_path, [f])

    vysledek = ingest.ingest(project, run)

    assert vysledek["counts"]["kept"] == 1
    assert vysledek["dropped"] == []


def test_nalez_bez_citace_neni_o_nic_lepsi_nez_bez_evidence(project, make_run):
    """Brána v jádru hlídá jen to, že evidence existuje. Že je to citace
    předpisu, hlídá metoda — a tenhle test drží, že prázdné pole neprojde
    ani u právního packu."""
    run = make_run(findings=[], pack="legal@0.1.0")
    f = make_finding(project, run.id, pack="legal@0.1.0", dimension="terms", evidence=[])
    write_json(run.findings_path, [f])

    vysledek = ingest.ingest(project, run)

    assert vysledek["counts"]["kept"] == 0
    assert vysledek["dropped"]


# ------------------------------------------------------------------- doctor

def test_doktor_hlasi_prazdnou_aplikacni_branu(project, capsys):
    legal = packs.load("legal")
    packs.apply(legal, project, packs.plan(legal, project),
                detected=agency_config.detect(project))

    kod = cli.cmd_doctor(SimpleNamespace(repo=str(project.root), json=False))

    vystup = capsys.readouterr().out
    assert kod == 1
    assert "business.model" in vystup and "business.size" in vystup


@pytest.mark.parametrize("model", ["marketplace", "eshop", "saas", "app", "content"])
def test_vyplnena_brana_uz_doktorovi_nechybi(project, model):
    legal = packs.load("legal")
    packs.apply(legal, project, packs.plan(legal, project))

    cli.cmd_config(SimpleNamespace(
        repo=str(project.root), json=True, pack="legal", unset=None,
        set_pairs=[f'business.model="{model}"', 'business.size="micro"']))

    cfg = project.pack_config("legal") or {}
    assert [k for k in legal.manifest["config"]["required"] if not cli._dig(cfg, k)] == []
