from agente.bot import LimitePorUsuario, a_html, usuario_anonimo


def test_a_html_negritas_y_escape():
    assert a_html("**La respuesta corta:** 1 < 2 & x") == "<b>La respuesta corta:</b> 1 &lt; 2 &amp; x"


def test_usuario_anonimo_estable_y_sin_id():
    assert usuario_anonimo(12345) == usuario_anonimo(12345)
    assert "12345" not in usuario_anonimo(12345) and len(usuario_anonimo(12345)) == 10


def test_limite_por_usuario():
    limite = LimitePorUsuario(maximo=2)
    assert limite.permitir(1) and limite.permitir(1) and not limite.permitir(1)
    assert limite.permitir(2)                                   # cada usuario tiene su propio límite
