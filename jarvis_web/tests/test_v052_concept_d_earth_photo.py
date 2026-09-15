from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_concept_d_real_earth_texture_exists() -> None:
    asset = ROOT / "web" / "public" / "assets" / "concept-d-earth-horizon.webp"
    assert asset.exists()
    assert asset.stat().st_size > 50_000


def test_frontend_uses_real_earth_texture_instead_of_css_city_dots() -> None:
    css = (ROOT / "web" / "src" / "styles.css").read_text(encoding="utf-8")
    core = (
        ROOT / "web" / "src" / "components" / "JarvisCoreVisual.tsx"
    ).read_text(encoding="utf-8")

    assert 'url("/assets/concept-d-earth-horizon.webp")' in css
    assert "earthCitiesOne" not in core
    assert "earthCitiesTwo" not in core
    assert "earthLatitude" not in core
    assert "background-size: 22px 19px" not in css
    assert "background-size: 47px 36px" not in css
