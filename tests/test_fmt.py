from stockproj.report import fmt


def test_price_has_thousands_separator():
    assert fmt.price(75300, "KR") == "75,300"
    assert fmt.price(1234567.4, "KR") == "1,234,567"
    assert fmt.price(1234.5, "US") == "1,234.50"
    assert fmt.price(float("nan"), "US") == "-"
    assert fmt.price(None, "KR") == "-"
