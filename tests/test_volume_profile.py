"""Pruebas del motor de Volume Profile (profitlab/volume_profile.py)."""
import numpy as np
import pytest

from profitlab import volume_profile as vp


def test_poc_en_el_precio_mas_negociado():
    # Tres barras: casi todo el volumen ocurre pegado a 100.
    high = [100.2, 100.2, 105.0]
    low = [99.8, 99.8, 95.0]
    close = [100.0, 100.0, 100.0]
    volume = [1000.0, 1000.0, 10.0]
    r = vp.compute(high, low, close, volume, bins=50)
    assert abs(r["poc"] - 100.0) < 0.5, r["poc"]


def test_value_area_contiene_la_fraccion_pedida():
    rng = np.random.default_rng(0)
    px = 100 + np.cumsum(rng.normal(0, 0.1, 400))
    high = px + 0.05
    low = px - 0.05
    close = px
    volume = rng.uniform(100, 1000, 400)
    r = vp.compute(high, low, close, volume, bins=60, value_area=0.70)
    # El volumen dentro de [VAL, VAH] debe ser >= 70% del total (±1 bin de holgura).
    price = np.asarray(r["price"])
    vols = np.asarray(r["volume"])
    inside = vols[(price >= r["val"]) & (price <= r["vah"])].sum()
    assert inside >= 0.68 * r["total_volume"]
    assert r["val"] <= r["poc"] <= r["vah"]


def test_conserva_el_volumen_total():
    high = [10.5, 11.0, 10.8]
    low = [9.5, 10.0, 9.9]
    close = [10.0, 10.5, 10.2]
    volume = [300.0, 500.0, 200.0]
    r = vp.compute(high, low, close, volume, bins=40)
    assert r["total_volume"] == pytest.approx(1000.0, rel=1e-9)


def test_reparte_el_volumen_de_una_barra_ancha():
    # Una sola barra que cubre 90..110 con 1000 de volumen: el volumen debe
    # quedar repartido (ningún bin se lleva el total).
    r = vp.compute([110.0], [90.0], [100.0], [1000.0], bins=20)
    vols = np.asarray(r["volume"])
    assert vols.max() < 1000.0
    assert vols.sum() == pytest.approx(1000.0, rel=1e-9)


def test_sesion_plana_no_rompe():
    # Precio constante (high==low==close): no debe dividir por cero.
    r = vp.compute([50.0] * 5, [50.0] * 5, [50.0] * 5, [100.0] * 5, bins=30)
    assert r["poc"] == pytest.approx(50.0, abs=1e-6)
    assert r["total_volume"] == pytest.approx(500.0, rel=1e-9)


def test_volumen_cero_no_rompe():
    r = vp.compute([10.0, 11.0], [9.0, 10.0], [9.5, 10.5], [0.0, 0.0], bins=10)
    assert r["total_volume"] == 0.0
    assert r["val"] <= r["vah"]


def test_sin_barras_lanza():
    with pytest.raises(ValueError):
        vp.compute([], [], [], [], bins=10)
