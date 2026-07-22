"""Tests del dossier para preguntar sobre inmuebles."""
from tests.conftest import requires_db
from src.services import qa_service as qa


@requires_db
def test_dossier_shape(sample_property_id):
    d = qa.dossier_public(sample_property_id)
    assert "caracteristicas" in d and "amenidades" in d
    assert "descripcion" in d and "nota" in d
    assert isinstance(d["amenidades"], list)


@requires_db
def test_dossier_no_existe():
    d = qa.dossier_public(999999999)
    assert "error" in d
