"""Testes da extração de contato — a regra que define o que entra no grupo.

Rodar: `python bot/tests/test_contatos.py` (só stdlib, sem pytest).

O que está em jogo aqui é falso positivo e falso negativo em cima do mesmo
texto: CPF e valor de contrato têm cara de telefone, e telefone aparece escrito
de sete jeitos diferentes. Cada caso abaixo saiu de anúncio real do ONM.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import contatos  # noqa: E402


def extrair(descricao: str = "", campo: str = "") -> list[contatos.Contato]:
    return contatos.extrair({"description": descricao, "proposalExternalLink": campo})


def tipos(cs: list[contatos.Contato]) -> list[str]:
    return [c.tipo for c in cs]


class TestTelefone(unittest.TestCase):
    def test_celular_com_ddd(self):
        c = extrair("chama no 81982626569")[0]
        self.assertEqual(c.tipo, "whatsapp")
        self.assertEqual(c.exibicao, "(81) 98262-6569")
        self.assertEqual(c.url, "https://wa.me/5581982626569")

    def test_celular_formatado(self):
        for escrito in ("(11) 98888-7777", "11 98888-7777", "11.98888.7777",
                        "+55 11 98888 7777", "5511988887777"):
            with self.subTest(escrito=escrito):
                achados = extrair(f"meu contato: {escrito}")
                self.assertEqual(len(achados), 1, escrito)
                self.assertEqual(achados[0].valor, "5511988887777")

    def test_fixo_vira_telefone_mas_com_zap_vira_whatsapp(self):
        self.assertEqual(extrair("ligue 11 3333-4444")[0].tipo, "telefone")
        self.assertEqual(extrair("whats 11 3333-4444")[0].tipo, "whatsapp")

    def test_numero_internacional_mantem_a_grafia_do_anuncio(self):
        c = extrair("pode chamar nesse número\n\n+353 83 408 4578")[0]
        self.assertEqual(c.tipo, "whatsapp")
        self.assertEqual(c.exibicao, "+353 83 408 4578")
        self.assertEqual(c.url, "https://wa.me/353834084578")

    def test_ddd_inexistente_nao_e_telefone(self):
        self.assertEqual(extrair("protocolo 30987654321"), [])

    def test_cpf_cnpj_cep_e_dinheiro_nao_sao_telefone(self):
        self.assertEqual(extrair("CPF 123.456.789-00"), [])
        self.assertEqual(extrair("CNPJ 12.345.678/0001-99"), [])
        self.assertEqual(extrair("pago R$ 1500,00 por mês"), [])
        self.assertEqual(extrair("orçamento de 2.500 a 3.000 reais"), [])

    def test_data_e_horario_nao_sao_telefone(self):
        self.assertEqual(extrair("entrega 13/08/2026 às 18:30"), [])


class TestLink(unittest.TestCase):
    def test_wa_me_vira_whatsapp_com_numero(self):
        c = extrair(campo="https://wa.me/5521971735005")[0]
        self.assertEqual(c.tipo, "whatsapp")
        self.assertEqual(c.exibicao, "(21) 97173-5005")

    def test_formulario(self):
        c = extrair(campo="https://forms.gle/cdAPEgNHioANJLTa9")[0]
        self.assertEqual(c.tipo, "link")
        self.assertEqual(c.exibicao, "forms.gle/cdAPEgNHioANJLTa9")

    def test_link_sem_protocolo_na_descricao(self):
        self.assertEqual(tipos(extrair("inscreva-se em forms.gle/abc123")), ["link"])

    def test_pontuacao_no_fim_do_link_nao_entra_na_url(self):
        c = extrair("candidate-se em https://empresa.com/vaga.")[0]
        self.assertEqual(c.url, "https://empresa.com/vaga")

    def test_telegram_e_instagram(self):
        self.assertEqual(tipos(extrair("chama em t.me/fulano")), ["telegram"])
        self.assertEqual(tipos(extrair("veja instagram.com/estudio")), ["instagram"])

    def test_numero_dentro_de_link_nao_e_extraido_duas_vezes(self):
        self.assertEqual(len(extrair("fale em https://wa.me/5511988887777")), 1)


class TestEmail(unittest.TestCase):
    def test_email_no_campo_e_na_descricao(self):
        self.assertEqual(tipos(extrair(campo="bruna@empresa.com")), ["email"])
        c = extrair("currículos para vagas@estudio.com.br")[0]
        self.assertEqual(c.url, "mailto:vagas@estudio.com.br")

    def test_email_nao_vira_arroba_de_instagram(self):
        self.assertEqual(tipos(extrair("mande para joao@empresa.com")), ["email"])


class TestSemContato(unittest.TestCase):
    def test_proposta_pela_plataforma_nao_conta(self):
        self.assertEqual(extrair("deixem a proposta com valor e portfólio"), [])
        self.assertEqual(extrair("Envie remuneração e portfólio.", campo=""), [])


class TestSugestaoDoClassificador(unittest.TestCase):
    def test_trecho_que_existe_no_anuncio_passa(self):
        texto = "chama no zap 81 98262-6569 que respondo"
        c = contatos.de_sugestao("81 98262-6569", texto)
        self.assertIsNotNone(c)
        self.assertEqual(c.valor, "5581982626569")  # type: ignore[union-attr]

    def test_trecho_reformatado_pelo_modelo_ainda_passa(self):
        texto = "chama no zap 81 98262-6569"
        self.assertIsNotNone(contatos.de_sugestao("(81) 98262-6569", texto))

    def test_numero_inventado_e_recusado(self):
        texto = "chama no zap 81 98262-6569"
        self.assertIsNone(contatos.de_sugestao("11 91111-2222", texto))


class TestOrdemEDeduplicacao(unittest.TestCase):
    def test_campo_vem_antes_da_descricao_e_nao_repete(self):
        cs = extrair(descricao="ou chama no 81982626569 mesmo",
                     campo="81982626569")
        self.assertEqual(len(cs), 1)
        self.assertEqual(cs[0].origem, "campo")

    def test_varios_contatos_diferentes_coexistem(self):
        cs = extrair(descricao="zap 81982626569 ou email vagas@x.com "
                               "ou https://forms.gle/abc")
        self.assertEqual(sorted(tipos(cs)), ["email", "link", "whatsapp"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
