"""
Клинический диагноз — программа для формулировки клинического диагноза
по правилам медицинской документации Российской Федерации.

Диагноз собирается по рубрикам: основное заболевание, осложнения,
сопутствующие заболевания, фоновое заболевание, конкурирующее или
сочетанное заболевание. К каждой заполненной строке добавляется код
МКБ-10. Готовая формулировка выводится единым текстом, который можно
скопировать в историю болезни.

Шаблоны (ХОБЛ, бронхиальная астма, гипертоническая болезнь, ИБС,
сахарный диабет 2 типа) подставляют типовую формулировку и код.
Справочник в подсказках — краткий, для частых состояний; недостающий
код можно ввести вручную.

Запуск: streamlit run app.py
"""

from __future__ import annotations

import inspect
import json

import streamlit as st

from diagnosis import (
    Diagnosis,
    Line,
    TemplateResult,
    build_asthma,
    build_copd,
    build_diabetes,
    build_hypertension,
    build_ihd,
    format_html,
    format_plain,
    is_valid_code,
    recommended_copd_code,
    review,
    split_codes,
)
from icd10_data import has_more_specific, lookup, search_icd

st.set_page_config(
    page_title="Клинический диагноз",
    page_icon="✚",
    layout="wide",
)


def _dialog(title: str):
    """Декоратор окна шаблона. Широкое окно — если эта версия Streamlit его умеет."""
    kwargs: dict = {}
    try:
        if "width" in inspect.signature(st.dialog).parameters:
            kwargs["width"] = "large"
    except (TypeError, ValueError):
        pass
    return st.dialog(title, **kwargs)


# Подписи полей шаблонов. Значение справа — то, что попадёт в формулировку или код.
COPD_STAGES = {
    "1": "GOLD 1 — ОФВ1 ≥ 80%",
    "2": "GOLD 2 — ОФВ1 50–79%",
    "3": "GOLD 3 — ОФВ1 30–49%",
    "4": "GOLD 4 — ОФВ1 < 30%",
}
COPD_GROUPS = {
    "A": "A — мало симптомов, редкие обострения",
    "B": "B — много симптомов, редкие обострения",
    "E": "E — частые обострения (GOLD с 2023 г.)",
    "C": "C — мало симптомов, частые обострения (схема до 2023 г.)",
    "D": "D — много симптомов, частые обострения (схема до 2023 г.)",
}
COPD_CODES = {
    "J44.1": "J44.1 — обострение",
    "J44.0": "J44.0 — обострение с инфекцией нижних дыхательных путей",
    "J44.8": "J44.8 — уточнённая ХОБЛ вне обострения",
    "J44.9": "J44.9 — ХОБЛ неуточнённая",
}
ASTHMA_FORMS = {
    "J45.0": "Аллергическая — J45.0",
    "J45.1": "Неаллергическая — J45.1",
    "J45.8": "Смешанная — J45.8",
    "J45.9": "Форму не уточнять — J45.9",
}
ASTHMA_SEVERITY = [
    "легкое интермиттирующее течение",
    "легкое персистирующее течение",
    "среднетяжелое персистирующее течение",
    "тяжелое персистирующее течение",
]
HTN_ORGANS = {
    "I10": "I10 — без поражения сердца и почек",
    "I11.9": "I11.9 — сердце, без сердечной недостаточности",
    "I11.0": "I11.0 — сердце, с сердечной недостаточностью",
    "I12.9": "I12.9 — почки, без почечной недостаточности",
    "I12.0": "I12.0 — почки, с почечной недостаточностью",
    "I13.9": "I13.9 — сердце и почки, без уточнения недостаточности",
    "I13.0": "I13.0 — сердце и почки, с сердечной недостаточностью",
    "I13.1": "I13.1 — сердце и почки, с почечной недостаточностью",
    "I13.2": "I13.2 — сердце и почки, с сердечной и почечной недостаточностью",
}
HTN_HF_CODES = {"I11.0", "I13.0", "I13.2"}
HTN_RENAL_CODES = {"I12.0", "I12.9", "I13.0", "I13.1", "I13.2", "I13.9"}
HTN_HEART_CODES = {"I11.0", "I11.9", "I13.0", "I13.1", "I13.2", "I13.9"}
CHF_STAGES = ["I", "IIА", "IIБ", "III"]
CHF_CLASSES = ["I", "II", "III", "IV"]
CKD_STAGES = ["не указывать", "С1", "С2", "С3а", "С3б", "С4", "С5"]
IHD_VARIANTS = {
    "I20.8": "Стенокардия напряжения — I20.8",
    "I20.9": "Стенокардия без уточнения формы — I20.9",
    "I20.0": "Нестабильная стенокардия — I20.0",
    "I25.2": "Постинфарктный кардиосклероз — I25.2",
}
IHD_LOCALIZATIONS = [
    "не указывать",
    "передняя стенка левого желудочка",
    "нижняя стенка левого желудочка",
    "боковая стенка левого желудочка",
    "задняя стенка левого желудочка",
    "неуточнённая локализация",
]
DM_THERAPY = [
    "не указывать",
    "на диетотерапии",
    "на пероральной сахароснижающей терапии",
    "на инсулинотерапии",
    "на комбинированной сахароснижающей терапии",
]
DM_TARGETS = {
    "не указывать": "не указывать",
    "6,5": "< 6,5%",
    "7,0": "< 7,0%",
    "7,5": "< 7,5%",
    "8,0": "< 8,0%",
}
DM_COMPENSATION = ["не указывать", "компенсированный", "субкомпенсированный", "декомпенсированный"]
DX_TYPES = [
    "Предварительный диагноз",
    "Клинический диагноз",
    "Заключительный клинический диагноз",
]

HINT_MAIN = (
    "Нозология, течение, стадия, степень, функциональный класс и фаза — словами. "
    "Код МКБ-10 введите вручную или выберите из подсказки: она ищет и по коду, и по названию. "
    "Подсказка — краткий справочник; если кода в ней нет, сверьте его с официальной МКБ-10."
)
HINT_COMB = (
    "Конкурирующее заболевание равнозначно основному: каждое само по себе могло определить "
    "госпитализацию или исход. Сочетанное значимо только вместе с основным. Пустая строка в текст не попадёт."
)
HINT_BG = (
    "Фоновое заболевание участвовало в возникновении или тяжёлом течении основного, "
    "но само не является его осложнением. Пример: гипертоническая болезнь при ишемической болезни сердца."
)
HINT_COMP = (
    "Только состояния, патогенетически связанные с основным заболеванием. "
    "Каждое осложнение — отдельная строка со своим кодом. Пустые строки не выводятся."
)
HINT_COMORB = (
    "Другие болезни, важные для ведения пациента, но не связанные с основным патогенетически "
    "и не объясняющие его течение."
)


def inject_css() -> None:
    st.markdown(
        """
<style>
header[data-testid="stHeader"] { background: #f4f6f8; }
.block-container { max-width: 1180px; padding-top: 4.25rem; padding-bottom: 2.4rem; }
footer { visibility: hidden; }
.stAppDeployButton { display: none; }
.app-head { margin: 0 0 0.85rem; }
.app-title {
  font-size: 1.85rem; font-weight: 650; letter-spacing: -0.02em;
  color: #17212b; line-height: 1.3; margin: 0;
}
.app-sub { margin: 0.4rem 0 0; color: #52606c; font-size: 1rem; line-height: 1.5; max-width: 52rem; }
.rubric-title { font-size: 1.05rem; font-weight: 650; color: #17212b; margin: 0 0 0.15rem; }
.rubric-title span {
  font-size: 0.75rem; font-weight: 650; color: #8a4b3c; margin-left: 0.45rem; letter-spacing: 0.01em;
}
div[data-testid="stCaptionContainer"] p { color: #5c6b78; line-height: 1.45; }
.dx-sheet {
  background: #fffcf7; border: 1px solid #e4dccd; border-radius: 12px;
  padding: 1.15rem 1.25rem 0.35rem; box-shadow: 0 1px 2px rgba(40, 32, 20, 0.04);
}
.dx-kicker {
  font-family: Georgia, "Times New Roman", serif; font-size: 1.28rem;
  color: #243044; margin: 0 0 0.85rem;
}
.dx-rubric { margin: 0 0 0.9rem; }
.dx-label {
  font-size: 0.72rem; font-weight: 650; letter-spacing: 0.06em;
  text-transform: uppercase; color: #6d655c; margin: 0 0 0.22rem;
}
.dx-text {
  font-family: Georgia, "Times New Roman", serif; font-size: 1.06rem;
  line-height: 1.45; color: #1d1a16;
}
.dx-item { margin: 0.18rem 0 0; }
.dx-n { font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; color: #6d655c; margin-right: 0.35rem; }
.dx-code {
  font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  font-size: 0.92em; font-weight: 650; color: #1e3a4c; white-space: nowrap;
}
.dx-empty {
  border: 1px dashed #c5ced6; border-radius: 12px; padding: 1.15rem 1.2rem;
  color: #52606c; background: #f8fafb; line-height: 1.5;
}
div[data-testid="stCustomComponentV1"] iframe { border: 0; }
</style>
""",
        unsafe_allow_html=True,
    )


def _allocate(prefix: str) -> str:
    st.session_state["_uid"] += 1
    return f"{prefix}{st.session_state['_uid']}"


def _new_row(prefix: str, kind: str | None = None) -> str:
    uid = _allocate(prefix)
    st.session_state[f"text_{uid}"] = ""
    st.session_state[f"code_{uid}"] = ""
    st.session_state[f"origin_{uid}"] = "manual"
    if kind:
        st.session_state[f"kind_{uid}"] = kind
    return uid


def initialize() -> None:
    """Пустая форма: по одной строке в необязательных рубриках, чтобы поля были на виду."""
    st.session_state["_ready"] = True
    st.session_state["_uid"] = 0
    st.session_state["dx_type"] = "Клинический диагноз"
    st.session_state["main_text"] = ""
    st.session_state["main_code"] = ""
    st.session_state["ids_comp"] = [_new_row("c")]
    st.session_state["ids_bg"] = [_new_row("b")]
    st.session_state["ids_comorb"] = [_new_row("s")]
    st.session_state["ids_comb"] = [_new_row("k", "Конкурирующее")]


def _drop_row_state(uid: str) -> None:
    for prefix in ("text_", "code_", "sug_", "origin_", "kind_"):
        st.session_state.pop(f"{prefix}{uid}", None)


def apply_pending() -> None:
    """
    Шаблон записывает результат в `_pending`, а подстановка происходит
    в начале следующего прогона — до создания полей. Иначе Streamlit
    не даёт менять значение уже нарисованного поля.
    Строки осложнений прошлого шаблона заменяются, строки, добавленные
    вручную, остаются.
    """
    data = st.session_state.pop("_pending", None)
    if not data:
        return
    st.session_state["main_text"] = data["main_text"]
    st.session_state["main_code"] = data["main_code"]
    st.session_state.pop("main_sug", None)
    kept = []
    for uid in st.session_state["ids_comp"]:
        if st.session_state.get(f"origin_{uid}") == "template":
            _drop_row_state(uid)
        else:
            kept.append(uid)
    fresh = []
    for item in data["complications"]:
        uid = _new_row("c")
        st.session_state[f"text_{uid}"] = item["text"]
        st.session_state[f"code_{uid}"] = item["code"]
        st.session_state[f"origin_{uid}"] = "template"
        fresh.append(uid)
    st.session_state["ids_comp"] = fresh + kept


def request_clear() -> None:
    st.session_state["_do_clear"] = True


def bootstrap() -> None:
    if st.session_state.pop("_do_clear", False):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.session_state["_toast"] = "Форма очищена."
    if not st.session_state.get("_ready"):
        initialize()
    apply_pending()


def add_row(ids_key: str, prefix: str, with_kind: bool = False) -> None:
    kind = "Конкурирующее" if with_kind else None
    st.session_state[ids_key].append(_new_row(prefix, kind))


def delete_row(ids_key: str, uid: str) -> None:
    st.session_state[ids_key] = [item for item in st.session_state[ids_key] if item != uid]
    _drop_row_state(uid)


def _apply_suggestion(code_key: str, sug_key: str) -> None:
    raw = st.session_state.get(sug_key, "")
    if not raw or raw == "—":
        return
    st.session_state[code_key] = raw.split("—", 1)[0].strip()


def _short_name(name: str, limit: int = 88) -> str:
    if len(name) <= limit:
        return name
    return name[: limit - 1] + "…"


def _needs_picker(token: str) -> bool:
    if not is_valid_code(token):
        return True
    if lookup(token):
        return False
    return has_more_specific(token)


def render_suggestions(code_key: str, text_key: str, sug_key: str) -> None:
    """Под полем кода: официальное название либо список, из которого код можно взять."""
    raw = st.session_state.get(code_key, "")
    text = st.session_state.get(text_key, "")
    tokens = split_codes(raw)
    if tokens and not any(_needs_picker(token) for token in tokens):
        bits = []
        for token in tokens:
            entry = lookup(token)
            if entry:
                bits.append(f"{entry.code} — {entry.name}")
            else:
                bits.append(f"{token} — нет в кратком справочнике, сверьте с официальной МКБ-10")
        st.caption("; ".join(bits))
        return

    matches = search_icd(raw, text, limit=6)
    if not matches:
        if raw.strip():
            st.caption("Нет совпадений. Код МКБ-10 выглядит как J44.1: буква, две цифры и при необходимости знак после точки.")
        return
    options = ["—"] + [f"{entry.code} — {_short_name(entry.name)}" for entry in matches]
    if st.session_state.get(sug_key) not in options:
        st.session_state[sug_key] = "—"
    label = "Подсказки по формулировке" if not str(raw).strip() else "Подсказки МКБ-10"
    st.selectbox(
        label,
        options,
        key=sug_key,
        on_change=_apply_suggestion,
        args=(code_key, sug_key),
        help="Выбор подставит код в поле. Код можно и просто вписать.",
    )


def render_main() -> None:
    with st.container(border=True):
        st.markdown(
            '<div class="rubric-title">Основное заболевание <span>обязательно</span></div>',
            unsafe_allow_html=True,
        )
        text_col, code_col = st.columns([6, 2.2], vertical_alignment="top")
        with text_col:
            st.text_area(
                "Формулировка основного заболевания",
                key="main_text",
                height=110,
                placeholder="Например: Хроническая обструктивная болезнь легких (ХОБЛ), GOLD 2, группа B, обострение",
            )
        with code_col:
            st.text_input("Код МКБ-10", key="main_code", placeholder="J44.1")
        render_suggestions("main_code", "main_text", "main_sug")
        st.caption(HINT_MAIN)


def render_rows(
    ids_key: str,
    prefix: str,
    *,
    placeholder: str,
    with_kind: bool = False,
) -> None:
    ids = st.session_state[ids_key]
    if not ids:
        st.caption("Пока нет ни одной строки.")
    else:
        head_text, head_code, _head_del = st.columns([6.1, 2.15, 0.7], vertical_alignment="bottom")
        head_text.caption("Формулировка")
        head_code.caption("Код МКБ-10")
        for uid in ids:
            if with_kind:
                st.selectbox(
                    "Тип",
                    ["Конкурирующее", "Сочетанное"],
                    key=f"kind_{uid}",
                    help="Конкурирующее равнозначно основному. Сочетанное важно только вместе с ним.",
                )
            text_col, code_col, del_col = st.columns([6.1, 2.15, 0.7], vertical_alignment="center")
            with text_col:
                st.text_area(
                    "Формулировка",
                    key=f"text_{uid}",
                    height=88,
                    placeholder=placeholder,
                    label_visibility="collapsed",
                )
            with code_col:
                st.text_input(
                    "Код МКБ-10",
                    key=f"code_{uid}",
                    placeholder="Код",
                    label_visibility="collapsed",
                )
            with del_col:
                st.button(
                    "×",
                    key=f"del_{uid}",
                    help="Удалить строку",
                    type="tertiary",
                    width=44,
                    on_click=delete_row,
                    args=(ids_key, uid),
                )
            render_suggestions(f"code_{uid}", f"text_{uid}", f"sug_{uid}")
    st.button(
        "Добавить строку",
        key=f"add_{ids_key}",
        on_click=add_row,
        args=(ids_key, prefix, with_kind),
    )


def collect_diagnosis() -> Diagnosis:
    competing: list[Line] = []
    combined: list[Line] = []
    for uid in st.session_state["ids_comb"]:
        line = Line(
            st.session_state.get(f"text_{uid}", ""),
            st.session_state.get(f"code_{uid}", ""),
        )
        if st.session_state.get(f"kind_{uid}") == "Сочетанное":
            combined.append(line)
        else:
            competing.append(line)

    def lines(ids_key: str) -> list[Line]:
        return [
            Line(st.session_state.get(f"text_{uid}", ""), st.session_state.get(f"code_{uid}", ""))
            for uid in st.session_state[ids_key]
        ]

    return Diagnosis(
        title=st.session_state["dx_type"],
        main=Line(st.session_state.get("main_text", ""), st.session_state.get("main_code", "")),
        competing=competing,
        combined=combined,
        background=lines("ids_bg"),
        complications=lines("ids_comp"),
        comorbid=lines("ids_comorb"),
    )


def copy_button(text: str) -> None:
    """
    Кнопка копирования в самой странице, не во фрейме.

    Фрейм Streamlit не показывает смену подписи и часто не получает буфер
    обмена. Текст уходит в скрипт как JSON, чтобы кавычки диагноза его не сломали.
    """
    payload = json.dumps(text, ensure_ascii=False)
    st.html(
        f"""
        <div class="dx-copy">
          <button class="dx-copy-btn" type="button">Скопировать диагноз</button>
        </div>
        <style>
          .dx-copy-btn {{
            width: 100%; height: 42px; margin-top: 0.35rem; border: 0; border-radius: 8px;
            background: #1e3a4c; color: #fff; cursor: pointer;
            font: 600 15px/1 "Segoe UI", "Helvetica Neue", Arial, sans-serif;
          }}
          .dx-copy-btn:hover {{ background: #163044; }}
          .dx-copy-btn.done {{ background: #1d6b45; }}
        </style>
        <script>
          (function () {{
            const root = document.currentScript && document.currentScript.parentElement;
            const btn = root ? root.querySelector(".dx-copy-btn") : null;
            if (!btn || btn.dataset.bound === "1") return;
            btn.dataset.bound = "1";
            const text = {payload};
            btn.addEventListener("click", async () => {{
              let ok = false;
              try {{
                await navigator.clipboard.writeText(text);
                ok = true;
              }} catch (err) {{
                try {{
                  const area = document.createElement("textarea");
                  area.value = text;
                  area.setAttribute("readonly", "");
                  area.style.position = "fixed";
                  area.style.top = "0";
                  area.style.left = "0";
                  area.style.opacity = "0";
                  document.body.appendChild(area);
                  area.focus();
                  area.select();
                  ok = document.execCommand("copy");
                  area.remove();
                }} catch (fallbackErr) {{
                  ok = false;
                }}
              }}
              btn.textContent = ok ? "Скопировано" : "Не удалось скопировать";
              btn.classList.toggle("done", ok);
              setTimeout(() => {{
                btn.textContent = "Скопировать диагноз";
                btn.classList.remove("done");
              }}, 1600);
            }});
          }})();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def render_preview() -> None:
    st.markdown('<div class="rubric-title">Готовая формулировка</div>', unsafe_allow_html=True)
    st.selectbox("Вид диагноза", DX_TYPES, key="dx_type")
    dx = collect_diagnosis()
    plain = format_plain(dx)
    if not plain.strip():
        st.markdown(
            '<div class="dx-empty">Здесь появится связный диагноз. Заполните основное заболевание '
            "или откройте шаблон: ХОБЛ, бронхиальная астма, гипертоническая болезнь, ИБС "
            "или сахарный диабет 2 типа. Пустые рубрики в текст не попадают.</div>",
            unsafe_allow_html=True,
        )
        return
    st.markdown(format_html(dx), unsafe_allow_html=True)
    copy_button(plain)
    notes = review(dx)
    if notes:
        with st.container(border=True):
            st.markdown("**На что обратить внимание**")
            for note in notes:
                st.markdown(f"- {note}")
    with st.expander("Текст для копирования"):
        st.caption("Если браузер не отдал буфер обмена кнопке выше, скопируйте текст отсюда.")
        st.code(plain.rstrip("\n"), language=None)


def _ensure(values: dict) -> None:
    for key, value in values.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _optional(value: str) -> str | None:
    return None if value == "не указывать" else value


def _show_template_result(result: TemplateResult, button_key: str) -> None:
    preview = Diagnosis(
        title=st.session_state.get("dx_type", "Клинический диагноз"),
        main=Line(result.main_text, result.main_code),
        complications=[Line(text, code) for text, code in result.complications],
    )
    st.markdown("**Так это войдёт в диагноз**")
    st.code(format_plain(preview).rstrip("\n"), language=None)
    for note in result.notes:
        st.caption(note)
    if st.button("Подставить в диагноз", type="primary", key=button_key, use_container_width=True):
        st.session_state["_pending"] = {
            "main_text": result.main_text,
            "main_code": result.main_code,
            "complications": [{"text": text, "code": code} for text, code in result.complications],
        }
        st.session_state["_toast"] = "Шаблон подставлен. Проверьте формулировку и код перед копированием."
        st.rerun()


def _degree_label(value: str) -> str:
    return "нет" if value == "нет" else f"{value} степени"


@_dialog("Шаблон: ХОБЛ")
def dialog_copd() -> None:
    _ensure(
        {
            "tpl_copd_stage": "2",
            "tpl_copd_group": "B",
            "tpl_copd_phenotype": "не указывать",
            "tpl_copd_phase": "обострение",
            "tpl_copd_infection": False,
            "tpl_copd_dn": "нет",
            "tpl_copd_cor": "нет",
        }
    )
    st.caption(
        "Стадия — по ОФВ1 после бронходилататора. Группа — по симптомам и обострениям за год. "
        "Группа E с 2023 года заменяет прежние C и D; C и D оставлены, если в отделении ещё пишут ABCD."
    )
    left, right = st.columns(2)
    with left:
        st.selectbox("Стадия", list(COPD_STAGES), format_func=lambda item: COPD_STAGES[item], key="tpl_copd_stage")
        st.selectbox("Группа", list(COPD_GROUPS), format_func=lambda item: COPD_GROUPS[item], key="tpl_copd_group")
        st.selectbox(
            "Фенотип",
            ["не указывать", "эмфизематозный", "бронхитический", "смешанный"],
            key="tpl_copd_phenotype",
        )
        st.selectbox(
            "Фаза",
            ["обострение", "стихающее обострение", "ремиссия"],
            key="tpl_copd_phase",
        )
    with right:
        st.checkbox("Острая инфекция нижних дыхательных путей", key="tpl_copd_infection")
        st.selectbox(
            "Дыхательная недостаточность",
            ["нет", "I", "II", "III"],
            format_func=_degree_label,
            key="tpl_copd_dn",
        )
        st.selectbox(
            "Хроническое лёгочное сердце",
            ["нет", "без уточнения", "компенсированное", "декомпенсированное"],
            format_func=lambda item: {
                "нет": "нет",
                "без уточнения": "есть, компенсацию не уточнять",
                "компенсированное": "компенсированное",
                "декомпенсированное": "декомпенсированное",
            }[item],
            key="tpl_copd_cor",
        )
        phase = st.session_state["tpl_copd_phase"]
        infection = bool(st.session_state["tpl_copd_infection"])
        signature = (phase, infection)
        recommended = recommended_copd_code(phase, infection)
        # Код сам следует за фазой и инфекцией, пока врач его специально не удержит.
        # Смена стадии или группы выбор кода не сбрасывает.
        if st.session_state.get("tpl_copd_sig") != signature or st.session_state.get("tpl_copd_code") not in COPD_CODES:
            st.session_state["tpl_copd_sig"] = signature
            st.session_state["tpl_copd_code"] = recommended
        st.selectbox("Код МКБ-10", list(COPD_CODES), format_func=lambda item: COPD_CODES[item], key="tpl_copd_code")
    st.caption(
        "J44.0 ставят при обострении с инфекцией нижних дыхательных путей, J44.1 — при другом обострении, "
        "J44.8 — когда стадия и группа указаны, а обострения нет. J44.9 — если ХОБЛ оставляют неуточнённой. "
        "Пневмонию при необходимости добавьте отдельной строкой осложнения: в J44.0 её может не быть."
    )
    result = build_copd(
        stage=st.session_state["tpl_copd_stage"],
        group=st.session_state["tpl_copd_group"],
        phenotype=_optional(st.session_state["tpl_copd_phenotype"]),
        phase=st.session_state["tpl_copd_phase"],
        infection=infection,
        respiratory_failure=st.session_state["tpl_copd_dn"],
        cor_pulmonale=st.session_state["tpl_copd_cor"],
        code=st.session_state["tpl_copd_code"],
    )
    _show_template_result(result, "tpl_copd_apply")


@_dialog("Шаблон: бронхиальная астма")
def dialog_asthma() -> None:
    _ensure(
        {
            "tpl_asthma_form": "J45.0",
            "tpl_asthma_severity": "среднетяжелое персистирующее течение",
            "tpl_asthma_control": "частично контролируемая",
            "tpl_asthma_phase": "обострение",
            "tpl_asthma_status": False,
            "tpl_asthma_dn": "нет",
        }
    )
    left, right = st.columns(2)
    with left:
        st.selectbox("Форма", list(ASTHMA_FORMS), format_func=lambda item: ASTHMA_FORMS[item], key="tpl_asthma_form")
        st.selectbox("Течение", ASTHMA_SEVERITY, key="tpl_asthma_severity")
        st.selectbox(
            "Контроль",
            ["контролируемая", "частично контролируемая", "неконтролируемая"],
            key="tpl_asthma_control",
        )
    with right:
        st.selectbox("Фаза", ["обострение", "ремиссия"], key="tpl_asthma_phase")
        st.checkbox("Астматический статус", key="tpl_asthma_status")
        st.selectbox(
            "Дыхательная недостаточность",
            ["нет", "I", "II", "III"],
            format_func=_degree_label,
            key="tpl_asthma_dn",
        )
    st.caption(
        "J45.0 — с преобладанием аллергического компонента, J45.1 — неаллергическая, "
        "J45.8 — смешанная, J45.9 — форма не уточнена. Астматический статус кодируют J46, этот код заменяет J45."
    )
    result = build_asthma(
        form_code=st.session_state["tpl_asthma_form"],
        severity=st.session_state["tpl_asthma_severity"],
        control=st.session_state["tpl_asthma_control"],
        phase=st.session_state["tpl_asthma_phase"],
        status_asthmaticus=bool(st.session_state["tpl_asthma_status"]),
        respiratory_failure=st.session_state["tpl_asthma_dn"],
    )
    _show_template_result(result, "tpl_asthma_apply")


@_dialog("Шаблон: гипертоническая болезнь")
def dialog_htn() -> None:
    _ensure(
        {
            "tpl_htn_stage": "II",
            "tpl_htn_degree": "2",
            "tpl_htn_risk": "3",
            "tpl_htn_organ": "I11.9",
            "tpl_htn_lvh": False,
            "tpl_htn_crisis": False,
            "tpl_htn_ckd": "не указывать",
            "tpl_htn_ckd_line": True,
            "tpl_htn_hf_stage": "IIА",
            "tpl_htn_hf_fc": "II",
        }
    )
    st.caption(
        "Стадия — по поражению органов, а не по цифрам давления. Степень — по уровню АД. "
        "Риск ССО — риск сердечно-сосудистых осложнений."
    )
    left, right = st.columns(2)
    with left:
        st.selectbox("Стадия", ["I", "II", "III"], format_func=lambda item: f"{item} стадия", key="tpl_htn_stage")
        st.selectbox(
            "Артериальная гипертензия",
            ["1", "2", "3", "контролируемая"],
            format_func=lambda item: "контролируемая, целевое АД достигнуто" if item == "контролируемая" else f"степень {item}",
            key="tpl_htn_degree",
        )
        st.selectbox(
            "Риск ССО",
            ["1", "2", "3", "4"],
            format_func=lambda item: {"1": "1 — низкий", "2": "2 — средний", "3": "3 — высокий", "4": "4 — очень высокий"}[item],
            key="tpl_htn_risk",
        )
    with right:
        st.selectbox(
            "Что определяет код",
            list(HTN_ORGANS),
            format_func=lambda item: HTN_ORGANS[item],
            key="tpl_htn_organ",
        )
        st.checkbox("Гипертонический криз", key="tpl_htn_crisis")
        organ = st.session_state["tpl_htn_organ"]
        if organ in HTN_HEART_CODES:
            st.checkbox("Гипертрофия левого желудочка", key="tpl_htn_lvh")
        if organ in HTN_HF_CODES:
            st.selectbox("Стадия ХСН", CHF_STAGES, key="tpl_htn_hf_stage")
            st.selectbox("Функциональный класс ХСН", CHF_CLASSES, format_func=lambda item: f"ФК {item}", key="tpl_htn_hf_fc")
        if organ in HTN_RENAL_CODES:
            st.selectbox("Стадия ХБП", CKD_STAGES, key="tpl_htn_ckd")
            st.checkbox("Вынести ХБП отдельным осложнением с кодом N18", key="tpl_htn_ckd_line")
    st.caption(
        "I — нет поражения органов-мишеней. II — бессимптомное поражение, сахарный диабет, ХБП С3, "
        "атеросклероз без клинических осложнений. III — уже перенесённые сердечно-сосудистые и "
        "цереброваскулярные болезни, ХБП С4–С5. Степень 1: 140–159/90–99; 2: 160–179/100–109; 3: от 180/110 мм рт. ст."
    )
    organ = st.session_state["tpl_htn_organ"]
    result = build_hypertension(
        stage=st.session_state["tpl_htn_stage"],
        degree=st.session_state["tpl_htn_degree"],
        risk=st.session_state["tpl_htn_risk"],
        organ_code=organ,
        heart_failure_stage=st.session_state["tpl_htn_hf_stage"] if organ in HTN_HF_CODES else None,
        heart_failure_class=st.session_state["tpl_htn_hf_fc"] if organ in HTN_HF_CODES else None,
        left_ventricular_hypertrophy=bool(st.session_state.get("tpl_htn_lvh")) and organ in HTN_HEART_CODES,
        ckd_stage=st.session_state["tpl_htn_ckd"] if organ in HTN_RENAL_CODES else None,
        ckd_as_complication=bool(st.session_state.get("tpl_htn_ckd_line", True)),
        crisis=bool(st.session_state["tpl_htn_crisis"]),
    )
    _show_template_result(result, "tpl_htn_apply")


@_dialog("Шаблон: ИБС")
def dialog_ihd() -> None:
    _ensure(
        {
            "tpl_ihd_variant": "I20.8",
            "tpl_ihd_fc": "II",
            "tpl_ihd_year": "",
            "tpl_ihd_loc": "не указывать",
            "tpl_ihd_angina": True,
            "tpl_ihd_hf": False,
            "tpl_ihd_hf_stage": "IIА",
            "tpl_ihd_hf_fc": "II",
        }
    )
    st.selectbox("Вариант", list(IHD_VARIANTS), format_func=lambda item: IHD_VARIANTS[item], key="tpl_ihd_variant")
    variant = st.session_state["tpl_ihd_variant"]
    left, right = st.columns(2)
    with left:
        if variant in {"I20.8", "I20.9"}:
            st.selectbox("Функциональный класс", CHF_CLASSES, format_func=lambda item: f"ФК {item}", key="tpl_ihd_fc")
        if variant == "I25.2":
            st.text_input("Год инфаркта", key="tpl_ihd_year", placeholder="например, 2019")
            st.selectbox("Локализация", IHD_LOCALIZATIONS, key="tpl_ihd_loc")
            st.checkbox("Добавить в текст стенокардию напряжения", key="tpl_ihd_angina")
            if st.session_state["tpl_ihd_angina"]:
                st.selectbox(
                    "Функциональный класс стенокардии",
                    CHF_CLASSES,
                    format_func=lambda item: f"ФК {item}",
                    key="tpl_ihd_fc",
                )
    with right:
        st.checkbox("Добавить ХСН в осложнения", key="tpl_ihd_hf")
        if st.session_state["tpl_ihd_hf"]:
            st.selectbox("Стадия ХСН", CHF_STAGES, key="tpl_ihd_hf_stage")
            st.selectbox("Функциональный класс ХСН", CHF_CLASSES, format_func=lambda item: f"ФК {item}", key="tpl_ihd_hf_fc")
    st.caption(
        "Стенокардию напряжения в российской практике относят к I20.8 «другие формы стенокардии». "
        "I20.9 — если форму не уточняют. Постинфарктный кардиосклероз кодируют I25.2; "
        "стенокардию тогда пишут в той же формулировке и вторым кодом I20 не дублируют. "
        "ФК I–IV — канадская классификация."
    )
    use_fc = variant in {"I20.8", "I20.9"} or (variant == "I25.2" and st.session_state["tpl_ihd_angina"])
    result = build_ihd(
        variant=variant,
        functional_class=st.session_state["tpl_ihd_fc"] if use_fc else None,
        infarct_year=st.session_state["tpl_ihd_year"] if variant == "I25.2" else "",
        localization=st.session_state["tpl_ihd_loc"] if variant == "I25.2" else None,
        include_angina=bool(st.session_state["tpl_ihd_angina"]) if variant == "I25.2" else False,
        heart_failure_stage=st.session_state["tpl_ihd_hf_stage"] if st.session_state["tpl_ihd_hf"] else None,
        heart_failure_class=st.session_state["tpl_ihd_hf_fc"] if st.session_state["tpl_ihd_hf"] else None,
    )
    _show_template_result(result, "tpl_ihd_apply")


@_dialog("Шаблон: сахарный диабет 2 типа")
def dialog_dm() -> None:
    _ensure(
        {
            "tpl_dm_therapy": "на пероральной сахароснижающей терапии",
            "tpl_dm_hba": "",
            "tpl_dm_target": "7,0",
            "tpl_dm_comp": "не указывать",
            "tpl_dm_kidney": False,
            "tpl_dm_eye": False,
            "tpl_dm_neuro": False,
            "tpl_dm_angio": False,
            "tpl_dm_eye_kind": "непролиферативная",
            "tpl_dm_ckd": "не указывать",
            "tpl_dm_ckd_line": True,
        }
    )
    left, right = st.columns(2)
    with left:
        st.selectbox("Терапия", DM_THERAPY, key="tpl_dm_therapy")
        st.text_input("HbA1c, если известен", key="tpl_dm_hba", placeholder="например, 8,2")
        st.selectbox("Целевой HbA1c", list(DM_TARGETS), format_func=lambda item: DM_TARGETS[item], key="tpl_dm_target")
        st.selectbox("Компенсация, если её всё ещё требуют в записи", DM_COMPENSATION, key="tpl_dm_comp")
    with right:
        st.checkbox("Диабетическая нефропатия", key="tpl_dm_kidney")
        if st.session_state["tpl_dm_kidney"]:
            st.selectbox("Стадия ХБП", CKD_STAGES, key="tpl_dm_ckd")
            st.checkbox("Вынести ХБП отдельным осложнением с кодом N18", key="tpl_dm_ckd_line")
        st.checkbox("Диабетическая ретинопатия", key="tpl_dm_eye")
        if st.session_state["tpl_dm_eye"]:
            st.selectbox(
                "Ретинопатия",
                ["непролиферативная", "препролиферативная", "пролиферативная", "неуточненная"],
                key="tpl_dm_eye_kind",
            )
        st.checkbox("Дистальная диабетическая полинейропатия", key="tpl_dm_neuro")
        st.checkbox("Диабетическая макроангиопатия", key="tpl_dm_angio")
    st.caption(
        "Без осложнений — E11.9. Одно осложнение: E11.2 почки, E11.3 глаза, E11.4 нервная система, "
        "E11.5 периферическое кровообращение. Несколько осложнений — E11.7. "
        "Стадии С3а и С3б в МКБ-10 имеют один код N18.3, стадию пишут словами."
    )
    therapy = _optional(st.session_state["tpl_dm_therapy"])
    result = build_diabetes(
        therapy=therapy,
        hba1c=st.session_state["tpl_dm_hba"],
        target=_optional(st.session_state["tpl_dm_target"]),
        compensation=_optional(st.session_state["tpl_dm_comp"]),
        nephropathy=bool(st.session_state["tpl_dm_kidney"]),
        retinopathy=st.session_state["tpl_dm_eye_kind"] if st.session_state["tpl_dm_eye"] else None,
        neuropathy=bool(st.session_state["tpl_dm_neuro"]),
        angiopathy=bool(st.session_state["tpl_dm_angio"]),
        ckd_stage=st.session_state["tpl_dm_ckd"] if st.session_state["tpl_dm_kidney"] else None,
        ckd_as_complication=bool(st.session_state["tpl_dm_ckd_line"]),
    )
    _show_template_result(result, "tpl_dm_apply")


def render_rules() -> None:
    with st.expander("Как устроены рубрики и откуда берётся код"):
        st.markdown(
            """
**Основное заболевание** — нозология, которая сама по себе или через осложнения определила обращение, госпитализацию или исход. В тексте указывают течение, стадию, степень, функциональный класс и фазу. Код МКБ-10 у основного заболевания один.

**Конкурирующее заболевание** — второе заболевание той же тяжести: каждое из двух само по себе могло определить госпитализацию или исход.

**Сочетанное заболевание** — значимо только вместе с основным. По отдельности ни оно, ни основное этот исход не объясняют.

**Фоновое заболевание** — не осложнение и не случайная находка. Оно участвовало в возникновении или неблагоприятном течении основного: сахарный диабет при атеросклерозе, гипертоническая болезнь при ишемической болезни сердца.

**Осложнения** — состояния, патогенетически связанные с основным заболеванием.

**Сопутствующие заболевания** — другие болезни. Они важны для лечения, но не связаны с основным патогенетически.

В готовом тексте рубрики идут в этом порядке. Пустая рубрика не выводится.

Код берут из МКБ-10, по которой заполняют учётные формы. Краткий справочник подсказывает частые коды; любой другой код можно вписать вручную. Стадия GOLD, функциональный класс, группа риска и целевой HbA1c в код не входят — их пишут словами.
"""
        )


def render_templates() -> None:
    title_col, clear_col = st.columns([4.2, 1.2], vertical_alignment="center")
    with title_col:
        st.markdown('<div class="rubric-title">Шаблоны</div>', unsafe_allow_html=True)
    with clear_col:
        st.button("Очистить форму", on_click=request_clear, use_container_width=True)
    buttons = st.columns(5)
    actions = (
        ("ХОБЛ", dialog_copd),
        ("Бронхиальная астма", dialog_asthma),
        ("Гипертоническая болезнь", dialog_htn),
        ("ИБС", dialog_ihd),
        ("Сахарный диабет 2 типа", dialog_dm),
    )
    for column, (label, opener) in zip(buttons, actions):
        with column:
            if st.button(label, use_container_width=True):
                opener()


def render_form() -> None:
    render_main()
    with st.container(border=True):
        st.markdown('<div class="rubric-title">Конкурирующее или сочетанное заболевание</div>', unsafe_allow_html=True)
        render_rows(
            "ids_comb",
            "k",
            placeholder="Например: Ишемический инсульт в бассейне левой средней мозговой артерии",
            with_kind=True,
        )
        st.caption(HINT_COMB)
    with st.container(border=True):
        st.markdown('<div class="rubric-title">Фоновое заболевание</div>', unsafe_allow_html=True)
        render_rows(
            "ids_bg",
            "b",
            placeholder="Например: Гипертоническая болезнь III стадии, риск ССО 4 (очень высокий)",
        )
        st.caption(HINT_BG)
    with st.container(border=True):
        st.markdown('<div class="rubric-title">Осложнения основного заболевания</div>', unsafe_allow_html=True)
        render_rows(
            "ids_comp",
            "c",
            placeholder="Например: Дыхательная недостаточность II степени",
        )
        st.caption(HINT_COMP)
    with st.container(border=True):
        st.markdown('<div class="rubric-title">Сопутствующие заболевания</div>', unsafe_allow_html=True)
        render_rows(
            "ids_comorb",
            "s",
            placeholder="Например: Хронический гастрит, ремиссия",
        )
        st.caption(HINT_COMORB)


def main() -> None:
    bootstrap()
    inject_css()
    notice = st.session_state.pop("_toast", None)
    st.markdown(
        '<div class="app-head"><div class="app-title">Клинический диагноз</div>'
        '<p class="app-sub">Формулировка по правилам медицинской документации Российской Федерации: '
        "рубрики диагноза и коды МКБ-10. Порядок такой: основное заболевание, при необходимости "
        "конкурирующее, сочетанное и фоновое, затем осложнения и сопутствующие.</p></div>",
        unsafe_allow_html=True,
    )
    if notice:
        st.toast(notice)
    render_rules()
    render_templates()
    st.divider()
    form_col, preview_col = st.columns([1.12, 0.88], gap="large")
    with form_col:
        render_form()
    with preview_col:
        render_preview()
    st.caption(
        "Формулировку и код сверяют с клиническими рекомендациями и официальной МКБ-10. "
        "Программа помогает собрать запись для истории болезни и не ставит диагноз."
    )


main()
