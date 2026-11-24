from datetime import date

from app.services.extraction import labels
from app.services.extraction.layout import find_labels, find_values
from app.services.extraction.normalize import parse_date
from app.services.pdf_text import Word, build_lines

from tests.helpers import make_doc


def test_lines_and_segments_split_columns():
    doc = make_doc([(100, [(40, "Nordwind Solutions Kft."), (300, "Kiállítás dátuma:"), (400, "2026.01.05.")])])
    line = doc.lines[0]
    assert [s.text for s in line.segments] == ["Nordwind Solutions Kft.", "Kiállítás dátuma:", "2026.01.05."]


def test_words_with_close_tops_form_one_line():
    doc = make_doc([(100, [(40, "Vevő")]), (101.5, [(300, "Számlaszám: X-1")])])
    assert len(doc.lines) == 1


def test_value_right_of_label_same_segment():
    doc = make_doc([(100, [(300, "Fizetési határidő: 2026.01.13.")])])
    assert find_values(doc, labels.RX["due_date"], parse_date) == [date(2026, 1, 13)]


def test_value_in_next_segment():
    doc = make_doc([(100, [(300, "Rechnungsdatum:"), (420, "10. März 2026")])])
    assert find_values(doc, labels.RX["issue_date"], parse_date) == [date(2026, 3, 10)]


def test_two_column_header_values_below_labels():
    # Két címke egymás mellett, eltérő magasságban; az értékek a saját oszlopukban, alattuk.
    doc = make_doc([
        (119, [(40, "Vevő"), (288, "Kiállítás dátuma")]),
        (125, [(423, "Fizetési határidő")]),
        (130, [(40, "NORDWIND SOLUTIONS KFT."), (288, "2026. június 24.")]),
        (138, [(423, "2026. július 2.")]),
    ])
    assert find_values(doc, labels.RX["issue_date"], parse_date) == [date(2026, 6, 24)]
    assert find_values(doc, labels.RX["due_date"], parse_date) == [date(2026, 7, 2)]


def test_bilingual_label_value_below():
    # „Kiállítás dátuma / Invoice date” – a fordítás nem érték, az érték alatta van.
    doc = make_doc([
        (119, [(288, "Kiállítás dátuma / Invoice date")]),
        (130, [(288, "2026.10.15.")]),
    ])
    assert find_values(doc, labels.RX["issue_date"], parse_date)[0] == date(2026, 10, 15)


def test_bilingual_label_value_inline():
    doc = make_doc([(100, [(300, "Teljesítés dátuma / Date of supply: 2026.03.09.")])])
    assert find_values(doc, labels.RX["supply_date"], parse_date)[0] == date(2026, 3, 9)


def test_value_far_below_is_not_taken():
    doc = make_doc([(100, [(300, "Due date")]), (200, [(300, "2026.03.09.")])])
    assert find_values(doc, labels.RX["due_date"], parse_date) == []


def test_value_in_other_column_below_is_not_taken():
    doc = make_doc([(100, [(300, "Due date")]), (110, [(40, "2026.03.09.")])])
    assert find_values(doc, labels.RX["due_date"], parse_date) == []


def test_label_must_start_segment():
    # A mondat közepén álló „invoice date” nem címke.
    doc = make_doc([(100, [(40, "Please quote the invoice date 2026.03.09. with payment")])])
    assert find_labels(doc, labels.RX["issue_date"]) == []


def test_overlapping_words_keep_stream_order():
    # Egymásra nyomtatott címke és érték: x szerint rendezve összekeverednének.
    ws = [
        Word("Total", 440, 470, 379, 390, 11, 1, 0),
        Word("due", 475, 495, 379, 390, 11, 1, 1),
        Word("8", 442, 449, 379, 390, 11, 1, 2),
        Word("743,00", 455, 490, 379, 390, 11, 1, 3),
        Word("GBP", 525, 545, 379, 390, 11, 1, 4),
    ]
    line = build_lines(ws, 1)[0]
    assert line.text == "Total due 8 743,00 GBP"
