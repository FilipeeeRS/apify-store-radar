"""Render the analysis as a Markdown file and as a static HTML page (pt-BR)."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from radar import metrics as m

STORE = "https://apify.com/"
TITLE_MAX = 60


@dataclass
class Link:
    text: str
    url: str


Cell = str | Link


@dataclass
class Table:
    title: str
    note: str
    headers: list[str]
    rows: list[list[Cell]]
    empty: str = "Sem dados ainda."


def _n(v) -> str:
    return "–" if v is None else f"{v:,.0f}".replace(",", ".")


def _pct(v) -> str:
    return "–" if v is None else f"{v * 100:.0f}%"


def _delta(v) -> str:
    return "–" if v is None else f"{v * 100:+.0f}%"


def _ratio(v) -> str:
    return "–" if v is None else f"{v:.2f}".replace(".", ",") + "×"


def _price(v) -> str:
    return "–" if v is None else "US$ " + f"{v:.4f}".rstrip("0").rstrip(".").replace(".", ",")


def _pii(v) -> str:
    return "⚠" if v is not None and v >= 0.5 else ""


def _short(text: str | None) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= TITLE_MAX else text[: TITLE_MAX - 1] + "…"


def _actor(slug: str) -> Link:
    return Link(slug, STORE + slug)


GLOSSARY = [
    ("Usuários 30d", "soma dos usuários únicos de cada Actor nos últimos 30 dias. A mesma pessoa pode contar em vários Actors: é um indicador de demanda, não uma contagem de pessoas."),
    ("Ativos", f"Actors com pelo menos {m.MIN_ACTIVE_USERS} usuários em 30 dias, a oferta que de fato concorre."),
    ("Δ7d", "variação dos usuários 7d contra o snapshot de 7 a 14 dias atrás, só entre Actors presentes nos dois (evita o viés de entrar e sair da janela)."),
    ("Devs", "desenvolvedores distintos no nicho: 10 Actors do mesmo dev são, na prática, 1 concorrente."),
    ("Ritmo", "(usuários 30d ÷ usuários 90d) do nicho dividido pelo mesmo número da loja toda. Acima de 1,00, o nicho concentra mais usuários recentes que o normal. Vale desde o primeiro dia, antes de existir Δ7d, mas Actors novos têm ritmo alto por construção: aponta nicho novo ou acelerando, confirme com o Δ7d."),
    ("Líder e % líder", "Actor com mais usuários 30d e a parcela dele na demanda do nicho."),
    ("% Apify", "parcela da demanda em Actors oficiais (apify/)."),
    ("% gap", f"parcela da demanda em Actors com {m.GAP_MIN_USERS}+ usuários e sucesso abaixo de {m.GAP_MAX_SUCCESS:.0%} (com {m.GAP_MIN_RUNS}+ execuções) ou nota abaixo de {str(m.GAP_MAX_RATING).replace('.', ',')} (com {m.GAP_MIN_REVIEWS}+ avaliações)."),
    ("Pessoal", "⚠ quando a maioria dos Actors do nicho parece tratar dado pessoal (perfis, e-mails, redes sociais). Heurística por palavras do título; não substitui análise de LGPD."),
    ("Alvo e nicho", "extraídos do título: o alvo é o site ou produto (instagram), o nicho soma o que se extrai dele (instagram reel). Heurística, confira o líder."),
    ("Cobertura", "cerca de 15 mil Actors mais populares (limite da API) mais as páginas de novidades; a API omite ~15% dos itens de cada página. A cauda longa está subestimada."),
]


def _intro(meta: dict) -> str:
    text = (
        f"Foto de {meta['latest']} · {_n(meta['actors'])} Actors coletados · "
        f"{_n(meta['with_users'])} com usuários nos últimos 30 dias · {_n(meta['users30'])} usuários 30d somados "
        f"({_pct(meta['apify_share'])} em Actors oficiais da Apify) · "
        f"{meta['snapshots']} snapshot(s) no histórico desde {meta['first']}"
    )
    if meta["ref"]:
        return text + f" · crescimento comparado com {meta['ref']}."
    return text + " · ainda sem 7 dias de histórico para medir crescimento semanal."


def build_tables(result: dict) -> list[Table]:
    meta = result["meta"]
    gap_reasons = []
    for g in result["gaps"]:
        reasons = []
        if g["runs30"] and g["runs30"] >= m.GAP_MIN_RUNS and g["success"] < m.GAP_MAX_SUCCESS:
            reasons.append(f"sucesso {g['success'] * 100:.0f}%")
        if g["reviews"] and g["reviews"] >= m.GAP_MIN_REVIEWS and g["rating"] < m.GAP_MAX_RATING:
            reasons.append(f"nota {g['rating']:.1f}".replace(".", ","))
        gap_reasons.append(" e ".join(reasons))

    if meta["ref"]:
        rising_note = (
            f"Alvos ordenados pela variação semanal de usuários 7d contra {meta['ref']} (Δ7d). "
            f"Mínimo de {m.MIN_NICHE_DEMAND} usuários 30d e {m.MIN_NICHE_ACTORS} Actors."
        )
    else:
        rising_note = (
            "Ainda sem snapshot com 7 dias: ordenado pelo ritmo (usuários 30d ÷ 90d relativo à loja). "
            f"O Δ7d aparece a partir do 8º dia. Mínimo de {m.MIN_NICHE_DEMAND} usuários 30d e {m.MIN_NICHE_ACTORS} Actors."
        )

    return [
        Table(
            "Nichos em alta",
            rising_note,
            ["Alvo", "Actors", "Devs", "Usuários 30d", "Δ7d", "Ritmo", "Líder", "% líder", "Pessoal"],
            [
                [r["name"], _n(r["actors"]), _n(r["owners"]), _n(r["users30"]), _delta(r["wow"]), _ratio(r["ritmo"]),
                 _actor(r["leader"]), _pct(r["top_share"]), _pii(r["pii_share"])]
                for r in result["rising"]
            ],
        ),
        Table(
            "Nichos pouco atendidos",
            f"Nichos (alvo + o que se extrai) com demanda de {m.MIN_NICHE_DEMAND}+ usuários 30d, no máximo {m.MAX_COMPETITORS} "
            f"Actors ativos, líder com até {m.MAX_TOP_SHARE:.0%} da demanda e Apify oficial com até {m.MAX_APIFY_SHARE:.0%}. "
            "Ordenado por usuários por Actor ativo.",
            ["Nicho", "Usuários 30d", "Ativos", "Devs", "Usuários por ativo", "Líder", "% líder", "% gap", "Preço mediano", "Pessoal"],
            [
                [r["name"], _n(r["users30"]), _n(r["active"]), _n(r["owners"]), _n(r["users_per_active"]), _actor(r["leader"]),
                 _pct(r["top_share"]), _pct(r["gap_share"]), _price(r["median_price"]), _pii(r["pii_share"])]
                for r in result["underserved"]
            ],
        ),
        Table(
            "Gaps de qualidade",
            "Actors com muitos usuários que falham com frequência ou têm nota baixa: espaço para um concorrente melhor.",
            ["Actor", "Título", "Nicho", "Usuários 30d", "Sucesso", "Nota", "Preço", "Motivo"],
            [
                [_actor(g["slug"]), _short(g["title"]), g["niche"], _n(g["users30"]), _pct(g["success"]),
                 "–" if not g["reviews"] else f"{g['rating']:.1f} ({g['reviews']})".replace(".", ","),
                 _price(g["price_usd"]), reason]
                for g, reason in zip(result["gaps"], gap_reasons)
            ],
        ),
        Table(
            "Entrantes recentes",
            f"Actors vistos pela primeira vez nos últimos {m.ENTRANT_DAYS} dias (depois do 1º snapshot), por usuários 30d. "
            "Quem aparece com ranking de novidades é lançamento recente de verdade.",
            ["Actor", "Título", "Nicho", "Usuários 30d", "Visto pela 1ª vez", "Ranking novidades"],
            [
                [_actor(e["slug"]), _short(e["title"]), e["niche"], _n(e["users30"]), str(e["first_seen"]), _n(e["rank_newest"])]
                for e in result["entrants"]
            ],
            empty="Aparece a partir do 2º snapshot.",
        ),
        Table(
            "Alvos com mais demanda",
            "Contexto: onde estão os usuários hoje (site ou produto-alvo extraído do título).",
            ["Alvo", "Actors", "Ativos", "Usuários 30d", "Líder", "% líder", "% Apify", "Pessoal"],
            [
                [r["name"], _n(r["actors"]), _n(r["active"]), _n(r["users30"]), _actor(r["leader"]),
                 _pct(r["top_share"]), _pct(r["apify_share"]), _pii(r["pii_share"])]
                for r in result["targets_demand"]
            ],
        ),
        Table(
            "Categorias da loja",
            "Um Actor pode ter mais de uma categoria e conta em todas.",
            ["Categoria", "Actors", "Ativos", "Usuários 30d", "Δ7d", "Ritmo", "Líder", "% líder"],
            [
                [r["name"], _n(r["actors"]), _n(r["active"]), _n(r["users30"]), _delta(r["wow"]), _ratio(r["ritmo"]),
                 _actor(r["leader"]), _pct(r["top_share"])]
                for r in result["categories"]
            ],
        ),
    ]


def _md(cell: Cell) -> str:
    if isinstance(cell, Link):
        return f"[{cell.text}]({cell.url})"
    return cell.replace("|", "\\|").replace("\n", " ")


def render_markdown(result: dict) -> str:
    out = [f"# Radar da Apify Store — {result['meta']['latest']}", "", _intro(result["meta"]), ""]
    for table in build_tables(result):
        out += [f"## {table.title}", "", table.note, ""]
        if table.rows:
            out.append("| " + " | ".join(table.headers) + " |")
            out.append("|" + "|".join("---" for _ in table.headers) + "|")
            out += ["| " + " | ".join(_md(c) for c in row) + " |" for row in table.rows]
        else:
            out.append(f"_{table.empty}_")
        out.append("")
    out += ["## Como ler", ""] + [f"- **{term}**: {text}" for term, text in GLOSSARY] + [""]
    return "\n".join(out)


_NUM = re.compile(r"^(?:US\$ )?[+\-]?[\d.,]+[%×]?$")
_CSS = """
:root{color-scheme:light dark;--bg:#fff;--fg:#1d2330;--mut:#667085;--line:#e4e7ec;--acc:#2a5bd7}
@media (prefers-color-scheme:dark){:root{--bg:#10141c;--fg:#e6e9ef;--mut:#98a2b3;--line:#262d3a;--acc:#7aa2ff}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6rem;margin:0 0 4px}h2{font-size:1.15rem;margin:32px 0 4px}
p{margin:0 0 8px}p.note,p.intro,.empty{color:var(--mut);font-size:.9rem}
.wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.88rem;font-variant-numeric:tabular-nums}
th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{font-weight:600;color:var(--mut)}th.num,td.num{text-align:right}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
dt{font-weight:600;margin-top:10px}dd{margin:0;color:var(--mut)}
"""


def _cell_html(cell: Cell, numeric: bool) -> str:
    if isinstance(cell, Link):
        return f'<td><a href="{html.escape(cell.url, quote=True)}" rel="noopener">{html.escape(cell.text)}</a></td>'
    return f'<td class="num">{html.escape(cell)}</td>' if numeric else f"<td>{html.escape(cell)}</td>"


def render_html(result: dict) -> str:
    meta = result["meta"]
    body = [f"<h1>Radar da Apify Store — {meta['latest']}</h1>", f'<p class="intro">{html.escape(_intro(meta))}</p>']
    for table in build_tables(result):
        body += [f"<h2>{html.escape(table.title)}</h2>", f'<p class="note">{html.escape(table.note)}</p>']
        if not table.rows:
            body.append(f'<p class="empty">{html.escape(table.empty)}</p>')
            continue
        # numeric columns: never the first one (a label, e.g. the niche "1688"), and every cell must look like a number
        nums = {
            i
            for i in range(1, len(table.headers))
            if all(isinstance(r[i], str) and (r[i] in ("", "–") or _NUM.match(r[i])) for r in table.rows)
        }
        head = "".join(f'<th class="num">{html.escape(h)}</th>' if i in nums else f"<th>{html.escape(h)}</th>" for i, h in enumerate(table.headers))
        rows = "".join("<tr>" + "".join(_cell_html(c, i in nums) for i, c in enumerate(row)) + "</tr>" for row in table.rows)
        body.append(f'<div class="wrap"><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>')
    body.append("<h2>Como ler</h2><dl>" + "".join(f"<dt>{html.escape(t)}</dt><dd>{html.escape(d)}</dd>" for t, d in GLOSSARY) + "</dl>")
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Radar da Apify Store — {meta['latest']}</title><style>{_CSS}</style></head>"
        f"<body><main>{''.join(body)}</main></body></html>"
    )
