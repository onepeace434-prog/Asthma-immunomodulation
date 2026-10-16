"""Тесты логики формулировки клинического диагноза."""

import pytest

from diagnosis import (
    Diagnosis,
    Line,
    build_asthma,
    build_copd,
    format_plain,
    is_valid_code,
    recommended_copd_code,
    review,
)


def test_is_valid_code():
    assert is_valid_code("J44.1")
    assert is_valid_code("I10")
    assert is_valid_code("E11.9")
    assert not is_valid_code("J44")
    assert not is_valid_code("44.1")
    assert not is_valid_code("J441")
    assert not is_valid_code("")


def test_recommended_copd_code():
    assert recommended_copd_code("ремиссия", False) == "J44.8"
    assert recommended_copd_code("обострение", False) == "J44.1"
    assert recommended_copd_code("обострение", True) == "J44.0"


def test_build_copd_basic():
    result = build_copd(
        stage="2",
        group="B",
        phenotype=None,
        phase="обострение",
        infection=False,
        respiratory_failure=None,
        cor_pulmonale=None,
        code="J44.1",
    )
    assert "ХОБЛ" in result.main_text
    assert "GOLD 2" in result.main_text
    assert "обострение" in result.main_text
    assert result.main_code == "J44.1"


def test_build_asthma_status():
    result = build_asthma(
        form_code="J45.0",
        severity="тяжелое персистирующее течение",
        control="неконтролируемая",
        phase="обострение",
        status_asthmaticus=True,
        respiratory_failure=None,
    )
    assert result.main_code == "J46"
    assert "астматический статус" in result.main_text.lower()


def test_format_plain_empty():
    dx = Diagnosis(title="Клинический диагноз")
    assert format_plain(dx) == ""


def test_format_plain_simple():
    dx = Diagnosis(
        title="Клинический диагноз",
        main=Line("Хроническая обструктивная болезнь легких, GOLD 2, группа B, обострение", "J44.1"),
    )
    text = format_plain(dx)
    assert "Клинический диагноз:" in text
    assert "Основное заболевание:" in text
    assert "J44.1" in text
    assert "ХОБЛ" in text or "обструктивная" in text.lower()


def test_review_missing_main():
    dx = Diagnosis(title="Клинический диагноз")
    notes = review(dx)
    assert any("Основное заболевание" in n for n in notes)


def test_review_copd_remission_mismatch():
    dx = Diagnosis(
        title="Клинический диагноз",
        main=Line("ХОБЛ, GOLD 2, ремиссия", "J44.1"),
    )
    notes = review(dx)
    assert any("ремисси" in n.lower() for n in notes)


def test_review_hypertension_hsn():
    dx = Diagnosis(
        title="Клинический диагноз",
        main=Line("Гипертоническая болезнь III стадии, ХСН IIА, ФК II", "I11.9"),
    )
    notes = review(dx)
    assert any("I11.0" in n or "сердечн" in n.lower() for n in notes)
