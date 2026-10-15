"""
Сборка текста клинического диагноза и шаблоны частых нозологий.

Порядок рубрик — тот, что принят в российской медицинской документации
для заключительного диагноза: основное заболевание, а вместе с ним
конкурирующее, сочетанное и фоновое; затем осложнения основного
заболевания; затем сопутствующие заболевания.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field


# Буквы, которые на русской раскладке выглядят как латинские в коде МКБ.
_HOMOGLYPHS = str.maketrans(
    {
        "А": "A",
        "В": "B",
        "С": "C",
        "Е": "E",
        "Н": "H",
        "К": "K",
        "М": "M",
        "О": "O",
        "Р": "P",
        "Т": "T",
        "Х": "X",
        "У": "Y",
    }
)

_CODE_RE = re.compile(r"^[A-Z]\d{2}(?:\.\d{1,2})?[*†]?$")
# Код в скобках в конце формулировки. «(высокий)» и «(2019 г.)» не совпадают:
# после скобки должен быть код вида J44.1.
_TRAILING_CODES = re.compile(
    r"(?:\s*\((?:[A-Za-zА-Я]\d{2}(?:\.\d{1,2})?[*†]?(?:\s*,\s*[A-Za-zА-Я]\d{2}(?:\.\d{1,2})?[*†]?)*)\)\.?)+$"
)


@dataclass
class Line:
    """Одна строка рубрики: формулировка и код."""

    text: str = ""
    code: str = ""


@dataclass
class Diagnosis:
    """Диагноз, уже разложенный по рубрикам."""

    title: str
    main: Line = field(default_factory=Line)
    competing: list[Line] = field(default_factory=list)
    combined: list[Line] = field(default_factory=list)
    background: list[Line] = field(default_factory=list)
    complications: list[Line] = field(default_factory=list)
    comorbid: list[Line] = field(default_factory=list)


@dataclass
class TemplateResult:
    """То, что шаблон подставляет в форму."""

    main_text: str
    main_code: str
    complications: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def normalize_code_token(raw: str) -> str:
    """Приводит один код к виду J44.1. Похожие русские буквы заменяет, если в строке есть цифра."""
    token = raw.strip().upper().replace(" ", "")
    if any(character.isdigit() for character in token):
        token = token.translate(_HOMOGLYPHS)
    return token


def split_codes(raw: str) -> list[str]:
    """Разбирает поле кода: один код или несколько через запятую."""
    if not raw or not raw.strip():
        return []
    tokens = []
    for part in re.split(r"[,;]+", raw):
        token = normalize_code_token(part)
        if token:
            tokens.append(token)
    return tokens


def codes_for_display(raw: str) -> str:
    return ", ".join(split_codes(raw))


def is_valid_code(token: str) -> bool:
    return bool(_CODE_RE.fullmatch(token))


def render_line(text: str, code: str) -> tuple[str, str]:
    """
    Собирает одну строку диагноза и её HTML.

    Код из отдельного поля ставится в скобках в конце. Если тот же код
    уже дописан в конце формулировки, он не повторяется. Скобки внутри
    текста («риск 3 (высокий)») сохраняются.
    """
    clean = re.sub(r"\s+", " ", text or "").strip()
    if code and code.strip():
        clean = _TRAILING_CODES.sub("", clean).strip()
    clean = clean.strip(" ;").rstrip(".")
    codes = codes_for_display(code)
    if not clean and not codes:
        return "", ""
    if clean and codes:
        plain = f"{clean} ({codes})."
        html_line = (
            f"{html.escape(clean)} "
            f'<span class="dx-code">({html.escape(codes)})</span>.'
        )
    elif clean:
        plain = f"{clean}."
        html_line = f"{html.escape(clean)}."
    else:
        plain = f"({codes})."
        html_line = f'<span class="dx-code">({html.escape(codes)})</span>.'
    return plain, html_line


def _filled(lines: list[Line]) -> list[tuple[str, str]]:
    rendered = []
    for line in lines:
        plain, html_line = render_line(line.text, line.code)
        if plain:
            rendered.append((plain, html_line))
    return rendered


def rubric_pairs(dx: Diagnosis) -> list[tuple[str, list[tuple[str, str]]]]:
    """Рубрики, в которых есть хотя бы одна непустая строка, в клиническом порядке."""
    main_lines = _filled([dx.main]) if (dx.main.text.strip() or dx.main.code.strip()) else []
    groups = (
        ("Основное заболевание", main_lines),
        ("Конкурирующее заболевание", _filled(dx.competing)),
        ("Сочетанное заболевание", _filled(dx.combined)),
        ("Фоновое заболевание", _filled(dx.background)),
        ("Осложнения основного заболевания", _filled(dx.complications)),
        ("Сопутствующие заболевания", _filled(dx.comorbid)),
    )
    return [(title, lines) for title, lines in groups if lines]


def format_plain(dx: Diagnosis) -> str:
    """Текст для истории болезни и буфера обмена."""
    rubrics = rubric_pairs(dx)
    if not rubrics:
        return ""
    blocks = [f"{dx.title}:"]
    for title, lines in rubrics:
        if len(lines) == 1:
            blocks.append(f"{title}: {lines[0][0]}")
        else:
            numbered = "\n".join(f"{index}. {plain}" for index, (plain, _) in enumerate(lines, 1))
            blocks.append(f"{title}:\n{numbered}")
    return "\n\n".join(blocks) + "\n"


def format_html(dx: Diagnosis) -> str:
    """Та же формулировка для листа на экране. Одна строка, без пустых абзацев Markdown."""
    parts = [
        '<div class="dx-sheet">',
        f'<div class="dx-kicker">{html.escape(dx.title)}</div>',
    ]
    for title, lines in rubric_pairs(dx):
        parts.append('<div class="dx-rubric">')
        parts.append(f'<div class="dx-label">{html.escape(title)}</div>')
        if len(lines) == 1:
            parts.append(f'<div class="dx-text">{lines[0][1]}</div>')
        else:
            parts.append('<div class="dx-text">')
            for index, (_, html_line) in enumerate(lines, 1):
                parts.append(
                    f'<div class="dx-item"><span class="dx-n">{index}.</span> {html_line}</div>'
                )
            parts.append("</div>")
        parts.append("</div>")
    parts.append("</div>")
    return "".join(parts)


def _blob(dx: Diagnosis) -> str:
    chunks = [dx.main.text]
    for group in (dx.competing, dx.combined, dx.background, dx.complications, dx.comorbid):
        chunks.extend(line.text for line in group)
    return re.sub(r"\s+", " ", " ".join(chunks)).lower().replace("ё", "е")


def review(dx: Diagnosis) -> list[str]:
    """
    Короткие замечания к формулировке.

    Это не запрет сохранить текст, а проверка частых несоответствий
    между словами и кодом.
    """
    notes: list[str] = []
    if not dx.main.text.strip() and not dx.main.code.strip():
        notes.append("Основное заболевание обязательно: без него формулировка неполная.")
    elif not dx.main.text.strip():
        notes.append("Есть код основного заболевания, но нет самой формулировки.")
    elif not split_codes(dx.main.code):
        notes.append("Для основного заболевания не указан код МКБ-10.")

    titles = (
        ("Основное заболевание", [dx.main]),
        ("Конкурирующее заболевание", dx.competing),
        ("Сочетанное заболевание", dx.combined),
        ("Фоновое заболевание", dx.background),
        ("Осложнения основного заболевания", dx.complications),
        ("Сопутствующие заболевания", dx.comorbid),
    )
    for title, lines in titles:
        for line in lines:
            for token in split_codes(line.code):
                if not is_valid_code(token):
                    notes.append(
                        f"В рубрике «{title}» значение «{token}» не похоже на код МКБ-10. Ожидается вид J44.1."
                    )

    tokens = split_codes(dx.main.code)
    main_code = tokens[0] if tokens else ""
    blob = _blob(dx)
    if main_code == "I11.9" and re.search(r"хсн|сердечн\w*\s+недостаточ", blob):
        notes.append(
            "Код I11.9 — гипертоническая болезнь с поражением сердца без сердечной недостаточности. "
            "Если ХСН есть, обычно выбирают I11.0."
        )
    if main_code == "I11.0" and not re.search(r"хсн|сердечн\w*\s+недостаточ", blob):
        notes.append(
            "Код I11.0 включает сердечную недостаточность. Напишите её в формулировке: "
            "стадию по Стражеско–Василенко и функциональный класс."
        )
    if main_code in {"J44.8", "J44.9"} and re.search(r"обострен", blob):
        notes.append(
            "В тексте есть обострение, а выбранный код его не отражает. "
            "При обострении обычно J44.1, при инфекции нижних дыхательных путей — J44.0."
        )
    if main_code == "J44.1" and re.search(r"ремисси", blob):
        notes.append(
            "Код J44.1 — ХОБЛ с обострением, а в тексте указана ремиссия. Вне обострения чаще ставят J44.8."
        )
    if main_code == "J44.0" and not re.search(r"инфек|пневмон", blob):
        notes.append(
            "Код J44.0 означает ХОБЛ с острой инфекцией нижних дыхательных путей. "
            "Напишите это в формулировке или смените код на J44.1."
        )
    if main_code == "E11.9" and re.search(
        r"нефропат|ретинопат|полинейропат|макроангиопат|диабетическ\w+\s+стоп",
        blob,
    ):
        notes.append(
            "Описаны осложнения сахарного диабета, а E11.9 — диабет без осложнений. "
            "При одном осложнении используют E11.2–E11.5, при нескольких — E11.7."
        )
    if main_code in {"I12.9", "I13.9"} and re.search(r"(?:хбп|стадия|ст\.)\s*с[45]\b", blob):
        notes.append(
            "Указана ХБП стадии С4 или С5, а код соответствует гипертонической болезни без почечной недостаточности. "
            "Обычно берут I12.0, I13.1 или I13.2."
        )
    return notes


def recommended_copd_code(phase: str, infection: bool) -> str:
    """J44.0 — инфекция нижних дыхательных путей, J44.1 — иное обострение, J44.8 — вне обострения."""
    if phase == "ремиссия":
        return "J44.8"
    if infection:
        return "J44.0"
    return "J44.1"


def _respiratory_failure(degree: str | None) -> tuple[str, str] | None:
    if not degree or degree == "нет":
        return None
    return (f"Дыхательная недостаточность {degree} степени", "J96.1")


def build_copd(
    *,
    stage: str,
    group: str,
    phenotype: str | None,
    phase: str,
    infection: bool,
    respiratory_failure: str | None,
    cor_pulmonale: str | None,
    code: str,
) -> TemplateResult:
    """ХОБЛ: стадия GOLD, группа, фаза и типичные осложнения."""
    phase_text = "ремиссия"
    if phase != "ремиссия":
        phase_text = "обострение" if phase == "обострение" else "стихающее обострение"
        if infection:
            phase_text += " с острой инфекцией нижних дыхательных путей"
    chunks = ["Хроническая обструктивная болезнь легких (ХОБЛ)"]
    if phenotype and phenotype != "не указывать":
        chunks.append(f"{phenotype} фенотип")
    chunks.append(f"GOLD {stage}")
    chunks.append(f"группа {group}")
    chunks.append(phase_text)
    complications: list[tuple[str, str]] = []
    failure = _respiratory_failure(respiratory_failure)
    if failure:
        complications.append(failure)
    if cor_pulmonale and cor_pulmonale != "нет":
        if cor_pulmonale == "без уточнения":
            complications.append(("Хроническое легочное сердце", "I27.9"))
        else:
            complications.append((f"Хроническое легочное сердце, {cor_pulmonale}", "I27.9"))
    notes = []
    if phase == "ремиссия" and infection:
        notes.append(
            "Инфекция нижних дыхательных путей меняет код на J44.0 только в обострении. "
            "Сейчас фаза — ремиссия, поэтому в текст она не добавлена."
        )
    if respiratory_failure and respiratory_failure != "нет":
        notes.append(
            "Дыхательная недостаточность при ХОБЛ обычно хроническая, код J96.1. "
            "Если она острая, замените код на J96.0 уже в форме."
        )
    return TemplateResult(", ".join(chunks), code, complications, notes)


def build_asthma(
    *,
    form_code: str,
    severity: str,
    control: str,
    phase: str,
    status_asthmaticus: bool,
    respiratory_failure: str | None,
) -> TemplateResult:
    """Бронхиальная астма по форме, тяжести, контролю и фазе."""
    form_words = {
        "J45.0": "аллергическая",
        "J45.1": "неаллергическая",
        "J45.8": "смешанная",
    }
    chunks = ["Бронхиальная астма"]
    form_word = form_words.get(form_code)
    if form_word and not status_asthmaticus:
        chunks.append(form_word)
    elif form_word:
        chunks.append(form_word)
    chunks.append(severity)
    chunks.append(control)
    if status_asthmaticus:
        chunks.append("астматический статус")
        code = "J46"
    else:
        chunks.append(phase)
        code = form_code
    complications: list[tuple[str, str]] = []
    failure = _respiratory_failure(respiratory_failure)
    if failure:
        complications.append(failure)
    notes = []
    if status_asthmaticus:
        notes.append("Астматический статус кодируют J46: этот код заменяет J45.")
    if respiratory_failure and respiratory_failure != "нет":
        notes.append("Для хронической дыхательной недостаточности указан J96.1. Острую кодируют J96.0.")
    return TemplateResult(", ".join(chunks), code, complications, notes)


_RISK_WORD = {"1": "низкий", "2": "средний", "3": "высокий", "4": "очень высокий"}
_HF_CODES = {"I11.0", "I13.0", "I13.2"}
_RENAL_CODES = {"I12.0", "I12.9", "I13.0", "I13.1", "I13.2", "I13.9"}
_CKD = {
    "С1": ("N18.1", "стадия С1"),
    "С2": ("N18.2", "стадия С2"),
    "С3а": ("N18.3", "стадия С3а"),
    "С3б": ("N18.3", "стадия С3б"),
    "С4": ("N18.4", "стадия С4"),
    "С5": ("N18.5", "стадия С5"),
}


def ckd_line(stage: str) -> tuple[str, str] | None:
    """Строка осложнения для стадии ХБП. С3а и С3б делят один код N18.3."""
    item = _CKD.get(stage)
    if not item:
        return None
    code, words = item
    return (f"Хроническая болезнь почек, {words}", code)


def build_hypertension(
    *,
    stage: str,
    degree: str,
    risk: str,
    organ_code: str,
    heart_failure_stage: str | None,
    heart_failure_class: str | None,
    left_ventricular_hypertrophy: bool,
    ckd_stage: str | None,
    ckd_as_complication: bool,
    crisis: bool,
) -> TemplateResult:
    """Гипертоническая болезнь: стадия, степень АГ, риск и поражение органов."""
    chunks = [f"Гипертоническая болезнь {stage} стадии"]
    if degree == "контролируемая":
        chunks.append("контролируемая артериальная гипертензия")
    else:
        chunks.append(f"степень АГ {degree}")
    chunks.append(f"риск ССО {risk} ({_RISK_WORD[risk]})")
    if crisis:
        chunks.append("гипертонический криз")
    if left_ventricular_hypertrophy:
        chunks.append("гипертрофия левого желудочка")
    if organ_code in _HF_CODES and heart_failure_stage and heart_failure_class:
        chunks.append(f"ХСН {heart_failure_stage} стадии, ФК {heart_failure_class}")
    complications: list[tuple[str, str]] = []
    if organ_code in _RENAL_CODES and ckd_stage and ckd_stage != "не указывать":
        line = ckd_line(ckd_stage)
        if line and ckd_as_complication:
            complications.append(line)
        elif line:
            chunks.append(f"хроническая болезнь почек, {line[0].split(', ', 1)[1]}")
    notes = []
    if stage == "I" and organ_code != "I10":
        notes.append("Поражение сердца или почек обычно соответствует II или III стадии, а не I.")
    if stage == "III" and organ_code == "I10":
        notes.append(
            "При III стадии, как правило, уже есть поражение органов-мишеней. "
            "Код I10 оставляют, когда сердце и почки кодировать нечем."
        )
    if left_ventricular_hypertrophy and organ_code == "I10":
        notes.append("Гипертрофия левого желудочка — поражение сердца. Для него обычно берут I11.9, а не I10.")
    if degree == "контролируемая" and crisis:
        notes.append("Контролируемая гипертензия и гипертонический криз в одной формулировке противоречат друг другу.")
    if organ_code in {"I12.9", "I13.9"} and ckd_stage in {"С4", "С5"}:
        notes.append(
            "Стадии С4 и С5 — почечная недостаточность. Код «без почечной недостаточности» лучше заменить на I12.0, I13.1 или I13.2."
        )
    if crisis:
        notes.append("Отдельного кода МКБ-10 для гипертонического криза нет: криз пишут словами, код остаётся кодом гипертонической болезни.")
    if organ_code in _HF_CODES:
        notes.append("Сердечная недостаточность входит в выбранный код, поэтому отдельная строка I50 не добавляется.")
    return TemplateResult(", ".join(chunks), organ_code, complications, notes)


def build_ihd(
    *,
    variant: str,
    functional_class: str | None,
    infarct_year: str,
    localization: str | None,
    include_angina: bool,
    heart_failure_stage: str | None,
    heart_failure_class: str | None,
) -> TemplateResult:
    """ИБС: стенокардия (I20.8 или I20.9), нестабильная стенокардия или постинфарктный кардиосклероз."""
    complications: list[tuple[str, str]] = []
    if variant == "I25.2":
        details = []
        if localization and localization != "не указывать":
            details.append(localization)
        year = infarct_year.strip()
        if year.isdigit():
            year = f"{year} г."
        if year:
            details.append(year)
        pics = "постинфарктный кардиосклероз"
        if details:
            pics += f" ({', '.join(details)})"
        chunks = [f"ИБС: {pics}"]
        if include_angina and functional_class:
            chunks.append(f"стенокардия напряжения, ФК {functional_class}")
        code = "I25.2"
    elif variant == "I20.0":
        chunks = ["ИБС: нестабильная стенокардия"]
        code = "I20.0"
    elif variant == "I20.9":
        chunks = ["ИБС: стенокардия"]
        if functional_class:
            chunks.append(f"ФК {functional_class}")
        code = "I20.9"
    else:
        chunks = ["ИБС: стенокардия напряжения"]
        if functional_class:
            chunks.append(f"ФК {functional_class}")
        code = "I20.8"
    if heart_failure_stage and heart_failure_class:
        complications.append(
            (f"ХСН {heart_failure_stage} стадии, ФК {heart_failure_class}", "I50.0")
        )
    notes = []
    if variant == "I25.2" and include_angina:
        notes.append(
            "Стенокардия оставлена в тексте, а код строки — I25.2. "
            "Второй код I20 не ставится, чтобы не получилось два основных заболевания."
        )
    if complications:
        notes.append("ХСН вынесена в осложнения с кодом I50.0 — застойная сердечная недостаточность.")
    return TemplateResult(", ".join(chunks), code, complications, notes)


def _format_hba1c(raw: str) -> str:
    value = raw.strip().replace(".", ",")
    if value.endswith("%"):
        value = value[:-1].strip()
    return value


def build_diabetes(
    *,
    therapy: str | None,
    hba1c: str,
    target: str | None,
    compensation: str | None,
    nephropathy: bool,
    retinopathy: str | None,
    neuropathy: bool,
    angiopathy: bool,
    ckd_stage: str | None,
    ckd_as_complication: bool,
) -> TemplateResult:
    """Сахарный диабет 2 типа. Код E11 зависит от числа и вида осложнений."""
    chunks = ["Сахарный диабет 2 типа"]
    if compensation:
        chunks.append(compensation)
    if therapy:
        chunks.append(therapy)
    actual = _format_hba1c(hba1c)
    if actual and target:
        chunks.append(f"HbA1c {actual}% при целевом уровне < {target}%")
    elif actual:
        chunks.append(f"HbA1c {actual}%")
    elif target:
        chunks.append(f"целевой уровень HbA1c < {target}%")
    flags = []
    if nephropathy:
        chunks.append("диабетическая нефропатия")
        flags.append("kidney")
    if retinopathy:
        if retinopathy == "неуточненная":
            chunks.append("диабетическая ретинопатия")
        else:
            chunks.append(f"{retinopathy} диабетическая ретинопатия")
        flags.append("eye")
    if neuropathy:
        chunks.append("дистальная диабетическая полинейропатия")
        flags.append("neuro")
    if angiopathy:
        chunks.append("диабетическая макроангиопатия")
        flags.append("circ")
    single = {"kidney": "E11.2", "eye": "E11.3", "neuro": "E11.4", "circ": "E11.5"}
    if not flags:
        code = "E11.9"
    elif len(flags) == 1:
        code = single[flags[0]]
    else:
        code = "E11.7"
    complications: list[tuple[str, str]] = []
    notes = []
    if nephropathy and ckd_stage and ckd_stage != "не указывать":
        line = ckd_line(ckd_stage)
        if line and ckd_as_complication:
            complications.append(line)
        elif line:
            chunks.append(f"хроническая болезнь почек, {line[0].split(', ', 1)[1]}")
        if ckd_stage in {"С3а", "С3б"}:
            notes.append("В МКБ-10 стадии С3а и С3б кодируются одним N18.3, поэтому стадия написана словами.")
    return TemplateResult(", ".join(chunks), code, complications, notes)


def self_check() -> None:
    plain, _ = render_line("ХОБЛ, GOLD 2, группа B, обострение", "j44.1")
    assert plain == "ХОБЛ, GOLD 2, группа B, обострение (J44.1).", plain
    plain, _ = render_line("ХОБЛ (J44.1)", "J44.1")
    assert plain == "ХОБЛ (J44.1).", plain
    plain, _ = render_line("риск 3 (высокий)", "I11.9")
    assert plain == "риск 3 (высокий) (I11.9).", plain
    assert codes_for_display("е11.9") == "E11.9"
    assert is_valid_code("J44.1")
    assert not is_valid_code("ХОБЛ")

    copd = build_copd(
        stage="2",
        group="B",
        phenotype=None,
        phase="обострение",
        infection=False,
        respiratory_failure=None,
        cor_pulmonale=None,
        code="J44.1",
    )
    assert copd.main_text == "Хроническая обструктивная болезнь легких (ХОБЛ), GOLD 2, группа B, обострение"
    assert recommended_copd_code("обострение", True) == "J44.0"
    assert recommended_copd_code("ремиссия", False) == "J44.8"
    infected = build_copd(
        stage="3",
        group="E",
        phenotype="бронхитический",
        phase="обострение",
        infection=True,
        respiratory_failure="II",
        cor_pulmonale="компенсированное",
        code="J44.0",
    )
    assert infected.main_text.endswith("обострение с острой инфекцией нижних дыхательных путей")
    assert infected.complications[0] == ("Дыхательная недостаточность II степени", "J96.1")
    assert infected.complications[1][1] == "I27.9"

    asthma = build_asthma(
        form_code="J45.0",
        severity="среднетяжелое персистирующее течение",
        control="частично контролируемая",
        phase="обострение",
        status_asthmaticus=False,
        respiratory_failure=None,
    )
    assert asthma.main_code == "J45.0"
    assert "аллергическая" in asthma.main_text
    status = build_asthma(
        form_code="J45.0",
        severity="тяжелое персистирующее течение",
        control="неконтролируемая",
        phase="обострение",
        status_asthmaticus=True,
        respiratory_failure=None,
    )
    assert status.main_code == "J46"
    assert "астматический статус" in status.main_text
    assert "обострение" not in status.main_text

    htn = build_hypertension(
        stage="II",
        degree="2",
        risk="3",
        organ_code="I11.9",
        heart_failure_stage=None,
        heart_failure_class=None,
        left_ventricular_hypertrophy=False,
        ckd_stage=None,
        ckd_as_complication=False,
        crisis=False,
    )
    assert htn.main_text == "Гипертоническая болезнь II стадии, степень АГ 2, риск ССО 3 (высокий)"
    assert htn.main_code == "I11.9"
    htn_hf = build_hypertension(
        stage="III",
        degree="3",
        risk="4",
        organ_code="I11.0",
        heart_failure_stage="II\u0410",
        heart_failure_class="III",
        left_ventricular_hypertrophy=False,
        ckd_stage=None,
        ckd_as_complication=False,
        crisis=False,
    )
    assert "ХСН II\u0410 стадии, ФК III" in htn_hf.main_text
    assert htn_hf.main_code == "I11.0"

    angina = build_ihd(
        variant="I20.8",
        functional_class="II",
        infarct_year="",
        localization=None,
        include_angina=False,
        heart_failure_stage=None,
        heart_failure_class=None,
    )
    assert angina.main_text == "ИБС: стенокардия напряжения, ФК II"
    assert angina.main_code == "I20.8"
    pics = build_ihd(
        variant="I25.2",
        functional_class="II",
        infarct_year="2019",
        localization="нижняя стенка левого желудочка",
        include_angina=True,
        heart_failure_stage=None,
        heart_failure_class=None,
    )
    assert pics.main_code == "I25.2"
    assert pics.main_text == (
        "ИБС: постинфарктный кардиосклероз (нижняя стенка левого желудочка, 2019 г.), "
        "стенокардия напряжения, ФК II"
    )

    dm = build_diabetes(
        therapy="на пероральной сахароснижающей терапии",
        hba1c="",
        target="7,0",
        compensation=None,
        nephropathy=False,
        retinopathy=None,
        neuropathy=False,
        angiopathy=False,
        ckd_stage=None,
        ckd_as_complication=False,
    )
    assert dm.main_code == "E11.9"
    assert dm.main_text == (
        "Сахарный диабет 2 типа, на пероральной сахароснижающей терапии, целевой уровень HbA1c < 7,0%"
    )
    dm_multi = build_diabetes(
        therapy="на инсулинотерапии",
        hba1c="8.4",
        target="7,5",
        compensation=None,
        nephropathy=True,
        retinopathy="непролиферативная",
        neuropathy=True,
        angiopathy=False,
        ckd_stage="С3а",
        ckd_as_complication=True,
    )
    assert dm_multi.main_code == "E11.7"
    assert "HbA1c 8,4%" in dm_multi.main_text
    assert dm_multi.complications == [("Хроническая болезнь почек, стадия С3а", "N18.3")]

    dx = Diagnosis(
        title="Клинический диагноз",
        main=Line(copd.main_text, copd.main_code),
        complications=[Line("Дыхательная недостаточность II степени", "J96.1")],
        background=[Line(htn.main_text, htn.main_code)],
        comorbid=[Line(dm.main_text, dm.main_code), Line("Хронический гастрит, ремиссия", "K29.5")],
    )
    text = format_plain(dx)
    assert text.index("Основное заболевание") < text.index("Фоновое заболевание")
    assert text.index("Фоновое заболевание") < text.index("Осложнения")
    assert text.index("Осложнения") < text.index("Сопутствующие")
    assert "1. " in text and "2. " in text
    assert "(J44.1)." in text
    assert "Конкурирующее" not in text
    contradiction = Diagnosis(title="Клинический диагноз", main=Line("Гипертоническая болезнь, ХСН IIА", "I11.9"))
    assert any("I11.0" in note for note in review(contradiction))


if __name__ == "__main__":
    self_check()
    print("Формулировки и шаблоны сходятся.")
