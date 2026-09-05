# ============================================================
# SISTEMA MALEX - app.py (Streamlit nativo)
# Segue o mesmo padrão do sistema de notas: tudo em um arquivo só,
# usando st.secrets para credenciais e a lib "supabase" (Python) para
# falar com o banco. Usa as MESMAS tabelas que o sistema já tinha
# (eventos, cadastros, produtos, vendas, usuarios, formas_pagamento) -
# nenhum dado existente é apagado ou precisa ser migrado.
#
# O que muda de comportamento em relação à versão HTML/JS:
#   - Impressão de Etiqueta e Recibo agora geram um PDF para baixar
#     (em vez de abrir uma janela do navegador com "Imprimir").
#   - Não existe mais modo offline: como o Streamlit roda no servidor,
#     é preciso estar online para usar o sistema.
#   - Configuração de impressora por evento agora fica salva no banco
#     (tabela config_impressora), porque não existe mais "localStorage
#     do navegador" no Streamlit. É só rodar o SQL novo (ver
#     SUPABASE_SETUP_STREAMLIT.sql) uma vez.
# ============================================================

import io
import base64
from datetime import datetime, date

import pandas as pd
import streamlit as st
import plotly.express as px
from supabase import create_client, Client

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as ImagemPDF
from reportlab.lib.styles import getSampleStyleSheet

# ---------------- Configuração básica ----------------

st.set_page_config(page_title="Sistema Malex", page_icon="📦", layout="wide")

SUPABASE_URL = "https://SEU-PROJETO.supabase.co"  # troque pela URL do seu projeto
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

MASTER_LOGIN = "Jess_"
MASTER_SENHA = "Jessyca_10"

PAGINAS_POR_CARGO = {
    "Master": ["Dashboard", "Eventos", "Usuários", "Guarda-volumes", "Vendas", "Relatórios", "Configurações", "Trocar senha"],
    "Supervisor": ["Dashboard", "Guarda-volumes", "Vendas", "Relatórios", "Trocar senha"],
    "Operador": ["Dashboard", "Guarda-volumes", "Vendas", "Trocar senha"],
}


# ---------------- Helpers gerais ----------------

def moeda(v):
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        v = 0
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def agora_iso():
    return datetime.now().isoformat()


def validar_cpf(cpf):
    cpf = "".join(filter(str.isdigit, str(cpf or "")))
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    dv1 = (soma * 10 % 11) % 10
    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    dv2 = (soma * 10 % 11) % 10
    return cpf[-2:] == f"{dv1}{dv2}"


def validar_cnpj(cnpj):
    cnpj = "".join(filter(str.isdigit, str(cnpj or "")))
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False

    def digito(base, pesos):
        soma = sum(int(base[i]) * pesos[i] for i in range(len(pesos)))
        resto = soma % 11
        return "0" if resto < 2 else str(11 - resto)

    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    dv1 = digito(cnpj, pesos1)
    if dv1 != cnpj[12]:
        return False
    dv2 = digito(cnpj, pesos2)
    return dv2 == cnpj[13]


def validar_cpf_cnpj(valor):
    numeros = "".join(filter(str.isdigit, str(valor or "")))
    if len(numeros) == 11:
        return validar_cpf(numeros)
    if len(numeros) == 14:
        return validar_cnpj(numeros)
    return False


def normalizar_malas(valor):
    if valor is None:
        return []
    if isinstance(valor, list):
        return valor
    if isinstance(valor, str):
        return [v.strip() for v in valor.split(",") if v.strip()]
    return []


def imagem_topo_pdf(evento, largura_max=160 * mm):
    """Converte o topo do evento (base64 salvo em eventos.topo_evento) em
    uma Image do reportlab, mantendo a proporção. Retorna None se o
    evento não tiver topo configurado ou se a imagem vier corrompida."""
    if not evento or not evento.get("topo_evento"):
        return None

    try:
        dados = evento["topo_evento"]
        if "," in dados:
            dados = dados.split(",", 1)[1]
        conteudo = base64.b64decode(dados)

        img = ImagemPDF(io.BytesIO(conteudo))
        proporcao = img.imageHeight / img.imageWidth
        img.drawWidth = largura_max
        img.drawHeight = largura_max * proporcao
        return img
    except Exception:
        return None


# ---------------- Sessão / autenticação ----------------

def init_session():
    if "usuario" not in st.session_state:
        st.session_state.usuario = None
    if "pagina" not in st.session_state:
        st.session_state.pagina = "Dashboard"


def buscar_usuario(usuario, senha):
    resp = (
        supabase.table("usuarios")
        .select("*")
        .eq("usuario", usuario)
        .eq("senha", senha)
        .execute()
    )
    dados = resp.data or []
    return dados[0] if dados else None


def nome_evento(evento_id):
    if not evento_id:
        return "Global"
    resp = supabase.table("eventos").select("nome").eq("id", evento_id).execute()
    dados = resp.data or []
    return dados[0]["nome"] if dados else "Evento não encontrado"


def tela_login():
    st.markdown(
        "<h1 style='text-align:center;margin-top:60px;'>Sistema Malex</h1>",
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        with st.form("form_login"):
            usuario = st.text_input("Usuário")
            senha = st.text_input("Senha", type="password")
            entrar = st.form_submit_button("Entrar", use_container_width=True)

        if entrar:
            if not usuario or not senha:
                st.error("Preencha usuário e senha.")
                return

            if usuario == MASTER_LOGIN and senha == MASTER_SENHA:
                st.session_state.usuario = {
                    "id": None,
                    "nome": "Jessyca",
                    "login": "Jess_",
                    "cargo": "Master",
                    "evento_id": None,
                    "evento_nome": "Global",
                    "permitir_edicao": True,
                    "permitir_exclusao": True,
                }
                st.session_state.pagina = "Dashboard"
                st.rerun()
                return

            dados = buscar_usuario(usuario, senha)

            if not dados:
                st.error("Usuário ou senha inválidos.")
                return

            if dados.get("ativo") is False:
                st.error("Usuário bloqueado.")
                return

            st.session_state.usuario = {
                "id": dados["id"],
                "nome": dados.get("nome"),
                "login": dados.get("usuario"),
                "cargo": dados.get("cargo"),
                "evento_id": dados.get("evento_id"),
                "evento_nome": nome_evento(dados.get("evento_id")),
                "permitir_edicao": bool(dados.get("permitir_edicao")),
                "permitir_exclusao": bool(dados.get("permitir_exclusao")),
            }

            if dados.get("primeiro_acesso") or dados.get("alterar_senha_obrigatoria"):
                st.session_state.pagina = "Trocar senha"
            else:
                st.session_state.pagina = "Dashboard"

            st.rerun()


def logout():
    st.session_state.usuario = None
    st.session_state.pagina = "Dashboard"
    st.rerun()


# ---------------- Sidebar / navegação ----------------

def sidebar():
    user = st.session_state.usuario

    with st.sidebar:
        st.markdown(f"### 📦 Sistema Malex")
        st.caption(f"{user['nome']} ({user['cargo']})")
        st.caption(f"Evento: {user['evento_nome']}")
        st.divider()

        opcoes = PAGINAS_POR_CARGO.get(user["cargo"], ["Dashboard"])
        if st.session_state.pagina not in opcoes:
            st.session_state.pagina = opcoes[0]

        pagina = st.radio("Menu", opcoes, index=opcoes.index(st.session_state.pagina), label_visibility="collapsed")
        st.session_state.pagina = pagina

        st.divider()
        if st.button("Sair", use_container_width=True):
            logout()

    return pagina


# ---------------- Eventos (dados auxiliares usados em várias telas) ----------------

def carregar_eventos(apenas_ativos=False):
    query = supabase.table("eventos").select("*").order("nome")
    resp = query.execute()
    eventos = resp.data or []
    if apenas_ativos:
        eventos = [e for e in eventos if e.get("status", "ativo") == "ativo"]
    return eventos


def carregar_evento(evento_id):
    if not evento_id:
        return None
    resp = supabase.table("eventos").select("*").eq("id", evento_id).execute()
    dados = resp.data or []
    return dados[0] if dados else None


def selecionar_evento(label, key, apenas_do_usuario=True, apenas_ativos=False):
    user = st.session_state.usuario
    eventos = carregar_eventos(apenas_ativos=apenas_ativos)

    if apenas_do_usuario and user["cargo"] != "Master":
        eventos = [e for e in eventos if str(e["id"]) == str(user["evento_id"])]

    if not eventos:
        st.info("Nenhum evento cadastrado.")
        return None

    opcoes = {e["nome"]: e["id"] for e in eventos}
    nomes = list(opcoes.keys())

    if apenas_do_usuario and user["cargo"] != "Master":
        escolhido = st.selectbox(label, nomes, key=key, disabled=True)
    else:
        escolhido = st.selectbox(label, nomes, key=key)

    return opcoes[escolhido]


# ---------------- Dashboard ----------------

def pagina_dashboard():
    st.title("Dashboard")

    evento_id = selecionar_evento("Evento", "evento_dashboard", apenas_ativos=False)
    if not evento_id:
        return

    resp = supabase.table("cadastros").select("*").eq("evento_id", evento_id).execute()
    cadastros = resp.data or []

    resp_usuarios = supabase.table("usuarios").select("id, nome").execute()
    usuarios = resp_usuarios.data or []

    if not cadastros:
        st.info("Nenhum cadastro de guarda-volumes para este evento ainda.")
        return

    df = pd.DataFrame(cadastros)
    df["dia"] = pd.to_datetime(df["created_at"]).dt.strftime("%d/%m/%Y")
    df["usuario_nome"] = df["usuario_id"].apply(
        lambda uid: next((u["nome"] for u in usuarios if str(u["id"]) == str(uid)), "Master")
    )

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Cadastros por dia")
        agr = df.groupby("dia").size().reset_index(name="quantidade")
        st.plotly_chart(px.pie(agr, names="dia", values="quantidade"), use_container_width=True)

    with col2:
        st.subheader("Volumes por dia")
        agr = df.groupby("dia")["quantidade_volumes"].sum().reset_index()
        st.plotly_chart(px.pie(agr, names="dia", values="quantidade_volumes"), use_container_width=True)

    col3, col4 = st.columns(2)

    with col3:
        st.subheader("Valor por dia (R$)")
        agr = df.groupby("dia")["valor_total"].sum().reset_index()
        st.plotly_chart(px.pie(agr, names="dia", values="valor_total"), use_container_width=True)

    with col4:
        st.subheader("Por forma de pagamento (R$)")
        agr = df.groupby("forma_pagamento")["valor_total"].sum().reset_index()
        st.plotly_chart(px.pie(agr, names="forma_pagamento", values="valor_total"), use_container_width=True)

    st.subheader("Cadastros por funcionário/dia")
    agr = df.groupby(["usuario_nome", "dia"]).size().reset_index(name="quantidade")
    agr["funcionario_dia"] = agr["usuario_nome"] + " - " + agr["dia"]
    st.plotly_chart(px.pie(agr, names="funcionario_dia", values="quantidade"), use_container_width=True)


# ---------------- Eventos ----------------

def carregar_formas_pagamento_master():
    resp = supabase.table("formas_pagamento").select("*").order("nome").execute()
    return resp.data or []


def carregar_produtos_evento(evento_id, apenas_ativos=True):
    query = supabase.table("produtos").select("*").eq("evento_id", evento_id).order("nome")
    if apenas_ativos:
        query = query.eq("ativo", True)
    resp = query.execute()
    return resp.data or []


@st.dialog("Produto")
def modal_produto(evento_id, produto=None):
    nome = st.text_input("Nome do produto", value=produto["nome"] if produto else "")
    valor = st.number_input("Valor", min_value=0.0, step=1.0, value=float(produto["valor"]) if produto else 0.0)
    descricao = st.text_input("Descrição (opcional)", value=produto.get("descricao") or "" if produto else "")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Salvar", use_container_width=True):
            if not nome or valor <= 0:
                st.error("Preencha nome e valor.")
                return
            if produto:
                supabase.table("produtos").update({"nome": nome, "valor": valor, "descricao": descricao}).eq("id", produto["id"]).execute()
            else:
                supabase.table("produtos").insert({"evento_id": evento_id, "nome": nome, "valor": valor, "descricao": descricao, "ativo": True}).execute()
            st.rerun()

    with col2:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()


def secao_formulario_produtos(evento_id):
    st.markdown("#### Formulário")

    if not evento_id:
        st.caption("Salve o evento primeiro para poder adicionar produtos.")
        return

    produtos = carregar_produtos_evento(evento_id)

    if not produtos:
        st.caption("Nenhum produto cadastrado ainda.")
    else:
        for p in produtos:
            c1, c2, c3 = st.columns([5, 1, 1])
            with c1:
                texto = f"**{p['nome']}** — {moeda(p['valor'])}"
                if p.get("descricao"):
                    texto += f"  \n{p['descricao']}"
                st.markdown(texto)
            with c2:
                if st.button("Editar", key=f"edit_prod_{p['id']}"):
                    modal_produto(evento_id, p)
            with c3:
                if st.button("Remover", key=f"del_prod_{p['id']}"):
                    supabase.table("produtos").update({"ativo": False}).eq("id", p["id"]).execute()
                    st.rerun()

    if st.button("+ Adicionar produto"):
        modal_produto(evento_id)


def pagina_eventos():
    st.title("Eventos")

    # ---- Formas de pagamento (lista mestre) ----
    st.subheader("Formas de Pagamento")
    st.caption("Crie formas de pagamento uma vez. Depois selecione quais serão usadas em cada evento.")

    col1, col2 = st.columns([3, 1])
    with col1:
        nova_forma = st.text_input("Ex.: PIX, Cartão, Dinheiro, Cortesia", key="nova_forma_pagamento", label_visibility="collapsed")
    with col2:
        if st.button("Criar forma de pagamento", use_container_width=True):
            if nova_forma.strip():
                supabase.table("formas_pagamento").insert({"nome": nova_forma.strip()}).execute()
                st.rerun()

    formas_master = carregar_formas_pagamento_master()
    st.write(", ".join(f["nome"] for f in formas_master) or "Nenhuma forma de pagamento cadastrada.")

    st.divider()

    # ---- Formulário de evento (novo ou edição) ----
    evento_editando = st.session_state.get("evento_editando_id")
    evt = carregar_evento(evento_editando) if evento_editando else None

    st.subheader("Editar Evento" if evt else "Novo Evento")

    nome_evt = st.text_input("Nome do Evento", value=evt["nome"] if evt else "")
    valor_volume = st.number_input("Valor por Volume", min_value=0.0, step=1.0, value=float(evt["valor_volume"]) if evt else 0.0)

    st.markdown("**Formas de Pagamento do Evento**")
    nomes_formas = [f["nome"] for f in formas_master]
    selecionadas = st.multiselect(
        "Selecione as formas que aparecerão para o operador",
        nomes_formas,
        default=(evt.get("formas_pagamento") or []) if evt else [],
    )
    forma_padrao = st.selectbox("Forma de pagamento padrão", selecionadas) if selecionadas else None

    col1, col2 = st.columns(2)
    with col1:
        opcoes_cpf = ["Não exibir", "Opcional", "Obrigatório"]
        idx_cpf = 0
        if evt:
            if evt.get("mostrar_cpf") and evt.get("cpf_obrigatorio"):
                idx_cpf = 2
            elif evt.get("mostrar_cpf"):
                idx_cpf = 1
        config_cpf = st.selectbox("CPF/CNPJ", opcoes_cpf, index=idx_cpf)
    with col2:
        opcoes_email = ["Não exibir", "Opcional", "Obrigatório"]
        idx_email = 0
        if evt:
            if evt.get("mostrar_email") and evt.get("email_obrigatorio"):
                idx_email = 2
            elif evt.get("mostrar_email"):
                idx_email = 1
        config_email = st.selectbox("E-mail", opcoes_email, index=idx_email)

    permitir_impressao = st.checkbox("Permitir impressão de etiqueta neste evento", value=evt["permitir_impressao"] if evt else True)

    topo = st.file_uploader("Topo do Evento (imagem)", type=["png", "jpg", "jpeg"])

    col1, col2 = st.columns(2)
    with col1:
        salvar = st.button("Salvar Evento", use_container_width=True, type="primary")
    with col2:
        limpar = st.button("Limpar", use_container_width=True)

    if limpar:
        st.session_state.evento_editando_id = None
        st.rerun()

    if salvar:
        if not nome_evt or valor_volume <= 0:
            st.error("Preencha nome e valor por volume.")
        else:
            dados_evento = {
                "nome": nome_evt,
                "valor_volume": valor_volume,
                "formas_pagamento": selecionadas,
                "forma_pagamento_padrao": forma_padrao,
                "mostrar_cpf": config_cpf != "Não exibir",
                "cpf_obrigatorio": config_cpf == "Obrigatório",
                "mostrar_email": config_email != "Não exibir",
                "email_obrigatorio": config_email == "Obrigatório",
                "permitir_impressao": permitir_impressao,
            }

            if topo is not None:
                import base64
                conteudo = topo.read()
                mime = topo.type
                dados_evento["topo_evento"] = f"data:{mime};base64,{base64.b64encode(conteudo).decode()}"

            if evt:
                supabase.table("eventos").update(dados_evento).eq("id", evt["id"]).execute()
                st.success("Evento atualizado.")
                st.session_state.evento_editando_id = evt["id"]
            else:
                resp = supabase.table("eventos").insert(dados_evento).execute()
                novo = resp.data[0] if resp.data else None
                st.success("Evento criado com sucesso!")
                if novo:
                    st.session_state.evento_editando_id = novo["id"]

            st.rerun()

    secao_formulario_produtos(evt["id"] if evt else None)

    st.divider()
    st.subheader("Eventos Cadastrados")

    for e in carregar_eventos():
        with st.container(border=True):
            c1, c2, c3 = st.columns([4, 1, 1])
            with c1:
                st.markdown(f"**{e['nome']}**  \nStatus: {e.get('status', 'ativo')} | Valor volume: {moeda(e['valor_volume'])}")
            with c2:
                if st.button("Editar", key=f"editar_evento_{e['id']}"):
                    st.session_state.evento_editando_id = e["id"]
                    st.rerun()
            with c3:
                novo_status = "inativo" if e.get("status", "ativo") == "ativo" else "ativo"
                if st.button(f"Marcar {novo_status}", key=f"status_evento_{e['id']}"):
                    supabase.table("eventos").update({"status": novo_status}).eq("id", e["id"]).execute()
                    st.rerun()


# ---------------- Usuários ----------------

def pagina_usuarios():
    st.title("Usuários")

    eventos = carregar_eventos()
    mapa_eventos = {e["id"]: e["nome"] for e in eventos}

    usuario_editando = st.session_state.get("usuario_editando_id")
    resp = supabase.table("usuarios").select("*").eq("id", usuario_editando).execute() if usuario_editando else None
    u = resp.data[0] if resp and resp.data else None

    st.subheader("Editar Usuário" if u else "Novo Usuário")

    nome = st.text_input("Nome", value=u["nome"] if u else "")
    login_usuario = st.text_input("Usuário (login)", value=u["usuario"] if u else "")
    senha = st.text_input("Senha", value="" if u else "", help="Deixe em branco para não alterar a senha atual" if u else None)
    cargo = st.selectbox("Cargo", ["Master", "Supervisor", "Operador"], index=["Master", "Supervisor", "Operador"].index(u["cargo"]) if u else 0)

    nomes_eventos = ["(Nenhum / Global)"] + list(mapa_eventos.values())
    idx_evento = 0
    if u and u.get("evento_id") in mapa_eventos:
        idx_evento = nomes_eventos.index(mapa_eventos[u["evento_id"]])
    evento_escolhido = st.selectbox("Evento vinculado", nomes_eventos, index=idx_evento)

    col1, col2 = st.columns(2)
    with col1:
        permitir_edicao = st.checkbox("Permitir editar registros", value=bool(u["permitir_edicao"]) if u else False)
    with col2:
        permitir_exclusao = st.checkbox("Permitir excluir registros", value=bool(u["permitir_exclusao"]) if u else False)

    ativo = st.checkbox("Usuário ativo", value=bool(u["ativo"]) if u else True)

    col1, col2 = st.columns(2)
    with col1:
        salvar = st.button("Salvar Usuário", use_container_width=True, type="primary")
    with col2:
        if st.button("Limpar", use_container_width=True):
            st.session_state.usuario_editando_id = None
            st.rerun()

    if salvar:
        if not nome or not login_usuario or (not u and not senha):
            st.error("Preencha nome, usuário e senha.")
        else:
            evento_id = None
            if evento_escolhido != "(Nenhum / Global)":
                evento_id = [k for k, v in mapa_eventos.items() if v == evento_escolhido][0]

            dados = {
                "nome": nome,
                "usuario": login_usuario,
                "cargo": cargo,
                "evento_id": evento_id,
                "permitir_edicao": permitir_edicao,
                "permitir_exclusao": permitir_exclusao,
                "ativo": ativo,
            }
            if senha:
                dados["senha"] = senha
                dados["primeiro_acesso"] = True
                dados["alterar_senha_obrigatoria"] = True

            if u:
                supabase.table("usuarios").update(dados).eq("id", u["id"]).execute()
                st.success("Usuário atualizado.")
            else:
                dados["senha"] = senha
                dados["primeiro_acesso"] = True
                dados["alterar_senha_obrigatoria"] = True
                supabase.table("usuarios").insert(dados).execute()
                st.success("Usuário criado.")

            st.session_state.usuario_editando_id = None
            st.rerun()

    st.divider()
    st.subheader("Usuários cadastrados")

    resp = supabase.table("usuarios").select("*").order("nome").execute()
    for usr in resp.data or []:
        with st.container(border=True):
            c1, c2, c3 = st.columns([4, 1, 1])
            with c1:
                evento_nome = mapa_eventos.get(usr.get("evento_id"), "Global")
                st.markdown(f"**{usr['nome']}** ({usr['cargo']}) — {evento_nome}  \nAtivo: {'Sim' if usr.get('ativo') else 'Não'}")
            with c2:
                if st.button("Editar", key=f"editar_usr_{usr['id']}"):
                    st.session_state.usuario_editando_id = usr["id"]
                    st.rerun()
            with c3:
                if st.button("Excluir", key=f"excluir_usr_{usr['id']}"):
                    supabase.table("usuarios").delete().eq("id", usr["id"]).execute()
                    st.rerun()


# ---------------- Geração de PDF (recibo e etiqueta) ----------------

def gerar_pdf_recibo(registro, tipo, evento):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=30, bottomMargin=30)
    estilos = getSampleStyleSheet()
    elementos = []

    topo = imagem_topo_pdf(evento)
    if topo:
        elementos.append(topo)
        elementos.append(Spacer(1, 10))

    elementos.append(Paragraph("RECIBO", estilos["Title"]))
    elementos.append(Paragraph(evento["nome"] if evento else "", estilos["Normal"]))
    elementos.append(Spacer(1, 14))

    linhas = [["Cliente", registro.get("nome", "")], ["Telefone", registro.get("telefone", "")]]

    if registro.get("cpf"):
        linhas.append(["CPF/CNPJ", registro.get("cpf")])
    if registro.get("email"):
        linhas.append(["E-mail", registro.get("email")])

    if tipo == "guarda_volumes":
        linhas.append(["Volumes", str(registro.get("quantidade_volumes", ""))])
        linhas.append(["Malas", ", ".join(normalizar_malas(registro.get("numeros_malas")))])
    else:
        linhas.append(["Produto", registro.get("produto_nome", "")])
        linhas.append(["Quantidade", str(registro.get("quantidade", ""))])

    linhas.append(["Pagamento", registro.get("forma_pagamento", "")])
    linhas.append(["Valor total", moeda(registro.get("valor_total"))])
    linhas.append(["Data", str(registro.get("created_at", ""))[:16].replace("T", " ")])

    tabela = Table(linhas, colWidths=[120, 320])
    tabela.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    elementos.append(tabela)

    doc.build(elementos)
    buffer.seek(0)
    return buffer


def gerar_pdf_etiquetas(registro, evento, config):
    largura = float(config.get("largura", 89)) * mm
    altura = float(config.get("altura", 40)) * mm

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=(largura, altura), topMargin=4 * mm, bottomMargin=4 * mm, leftMargin=4 * mm, rightMargin=4 * mm)
    estilos = getSampleStyleSheet()

    malas = normalizar_malas(registro.get("numeros_malas"))
    elementos = []

    for i, numero in enumerate(malas):
        elementos.append(Paragraph("<b>MALEX</b>", estilos["Normal"]))
        elementos.append(Paragraph(evento["nome"] if evento else "", estilos["Normal"]))
        elementos.append(Paragraph(f"<b>MALA {numero}</b>", estilos["Heading2"]))
        elementos.append(Paragraph(registro.get("nome", ""), estilos["Normal"]))
        elementos.append(Paragraph(registro.get("telefone", ""), estilos["Normal"]))
        elementos.append(Paragraph(f"{i + 1}/{len(malas)}", estilos["Normal"]))
        elementos.append(Paragraph("JRTecnologia", estilos["Normal"]))
        if i < len(malas) - 1:
            elementos.append(Spacer(1, 1))

    doc.build(elementos)
    buffer.seek(0)
    return buffer


def carregar_config_impressora(evento_id):
    resp = supabase.table("config_impressora").select("*").eq("evento_id", evento_id).execute()
    dados = resp.data or []
    if dados:
        return dados[0]
    return {"nome": "Argox", "largura": 89, "altura": 40, "margem": 4, "fonte_mala": 24}


def malas_ja_usadas(evento_id):
    resp = supabase.table("cadastros").select("numeros_malas").eq("evento_id", evento_id).execute()
    usadas = []
    for c in resp.data or []:
        usadas.extend(normalizar_malas(c.get("numeros_malas")))
    return set(usadas)


# ---------------- Guarda-volumes ----------------

def pagina_guarda_volumes():
    st.title("Guarda-volumes")

    user = st.session_state.usuario
    evento_id = selecionar_evento("Evento", "evento_gv", apenas_ativos=True)
    if not evento_id:
        return

    evento = carregar_evento(evento_id)

    st.subheader("Novo Cadastro")

    nome = st.text_input("Nome", key="gv_nome")
    telefone = st.text_input("Telefone", key="gv_telefone", placeholder="(11) 99999-9999")

    cpf = email = ""
    if evento.get("mostrar_cpf"):
        cpf = st.text_input("CPF/CNPJ" + (" *" if evento.get("cpf_obrigatorio") else " (opcional)"), key="gv_cpf")
    if evento.get("mostrar_email"):
        email = st.text_input("E-mail" + (" *" if evento.get("email_obrigatorio") else " (opcional)"), key="gv_email")

    qtd = st.number_input("Quantidade de volumes", min_value=1, step=1, value=1, key="gv_qtd")

    st.caption("Números das malas (separados por vírgula). Ex.: 001, 002, 003")
    malas_texto = st.text_input("Números das malas", key="gv_malas")

    formas = evento.get("formas_pagamento") or []
    forma_pagamento = st.selectbox("Forma de pagamento", formas, key="gv_pagamento") if formas else None

    observacoes = st.text_input("Observações", key="gv_obs")

    valor_total = qtd * float(evento.get("valor_volume") or 0)
    st.markdown(f"**Total: {moeda(valor_total)}**")

    if st.button("Registrar Cadastro", type="primary"):
        malas = [m.strip() for m in malas_texto.split(",") if m.strip()]

        if not nome or not telefone:
            st.error("Preencha nome e telefone.")
        elif len(malas) != qtd:
            st.error(f"Você informou {qtd} volume(s), mas digitou {len(malas)} número(s) de mala.")
        elif evento.get("cpf_obrigatorio") and not cpf:
            st.error("CPF/CNPJ é obrigatório neste evento.")
        elif cpf and not validar_cpf_cnpj(cpf):
            st.error("CPF/CNPJ inválido.")
        elif evento.get("email_obrigatorio") and not email:
            st.error("E-mail é obrigatório neste evento.")
        elif not forma_pagamento:
            st.error("Selecione uma forma de pagamento.")
        else:
            usadas = malas_ja_usadas(evento_id)
            repetida = next((m for m in malas if m in usadas), None)
            if repetida:
                st.error(f"A mala {repetida} já está em uso neste evento.")
            else:
                supabase.table("cadastros").insert({
                    "evento_id": evento_id,
                    "usuario_id": user["id"],
                    "nome": nome,
                    "telefone": telefone,
                    "cpf": cpf,
                    "email": email,
                    "quantidade_volumes": qtd,
                    "numeros_malas": malas,
                    "forma_pagamento": forma_pagamento,
                    "valor_total": valor_total,
                    "retirado": False,
                    "data_retirada": None,
                    "observacoes": observacoes,
                }).execute()
                st.success("Cadastro registrado com sucesso!")
                st.rerun()

    st.divider()
    st.subheader("Cadastros")

    col1, col2 = st.columns([1, 3])
    with col1:
        tipo_pesquisa = st.selectbox("Buscar por", ["nome", "telefone", "cpf", "mala"], key="gv_tipo_pesquisa")
    with col2:
        pesquisa = st.text_input("Pesquisar", key="gv_pesquisa")

    resp = supabase.table("cadastros").select("*").eq("evento_id", evento_id).order("created_at", desc=True).execute()
    registros = resp.data or []

    if pesquisa:
        p = pesquisa.lower()
        if tipo_pesquisa == "mala":
            registros = [r for r in registros if p in ",".join(normalizar_malas(r.get("numeros_malas"))).lower()]
        else:
            registros = [r for r in registros if p in str(r.get(tipo_pesquisa, "")).lower()]

    config_impressora = carregar_config_impressora(evento_id)

    for r in registros:
        with st.container(border=True):
            malas_r = normalizar_malas(r.get("numeros_malas"))
            status = "🟢 Retirado" if r.get("retirado") else "🟡 Pendente"

            col_info, col_acoes = st.columns([5, 1])

            with col_info:
                st.markdown(
                    f"**{r['nome']}** — {r['telefone']}  \n"
                    f"Volumes: {r['quantidade_volumes']} (malas: {', '.join(malas_r)}) | "
                    f"{r.get('forma_pagamento','')} | {moeda(r.get('valor_total'))} | {status}"
                )

            pode_editar = user["cargo"] == "Master" or user.get("permitir_edicao")
            pode_excluir = user["cargo"] == "Master" or user.get("permitir_exclusao")

            with col_acoes:
                with st.popover("•••", use_container_width=True):
                    if st.button("Ver detalhes", key=f"detalhes_gv_{r['id']}", use_container_width=True):
                        st.session_state[f"mostrar_detalhes_gv_{r['id']}"] = not st.session_state.get(f"mostrar_detalhes_gv_{r['id']}", False)

                    pdf_recibo = gerar_pdf_recibo(r, "guarda_volumes", evento)
                    st.download_button("Recibo (PDF)", pdf_recibo, file_name=f"recibo_{r['id']}.pdf", mime="application/pdf", key=f"recibo_{r['id']}", use_container_width=True)

                    if evento.get("permitir_impressao") and malas_r:
                        pdf_etq = gerar_pdf_etiquetas(r, evento, config_impressora)
                        st.download_button("Etiqueta (PDF)", pdf_etq, file_name=f"etiqueta_{r['id']}.pdf", mime="application/pdf", key=f"etiqueta_{r['id']}", use_container_width=True)

                    if not r.get("retirado"):
                        if st.button("Marcar retirado", key=f"retirado_{r['id']}", use_container_width=True):
                            supabase.table("cadastros").update({"retirado": True, "data_retirada": agora_iso()}).eq("id", r["id"]).execute()
                            st.rerun()
                    else:
                        if st.button("Marcar pendente", key=f"pendente_{r['id']}", use_container_width=True):
                            supabase.table("cadastros").update({"retirado": False, "data_retirada": None}).eq("id", r["id"]).execute()
                            st.rerun()

                    if pode_editar:
                        if st.button("Editar", key=f"editar_gv_{r['id']}", use_container_width=True):
                            st.session_state[f"editando_gv_{r['id']}"] = True

                    if pode_excluir:
                        if st.button("Excluir", key=f"excluir_gv_{r['id']}", use_container_width=True):
                            supabase.table("cadastros").delete().eq("id", r["id"]).execute()
                            st.rerun()

            if st.session_state.get(f"mostrar_detalhes_gv_{r['id']}"):
                st.markdown(
                    f"**CPF/CNPJ:** {r.get('cpf') or '-'}  \n"
                    f"**E-mail:** {r.get('email') or '-'}  \n"
                    f"**Data do cadastro:** {str(r.get('created_at') or '')[:16].replace('T', ' ')}  \n"
                    f"**Data de retirada:** {str(r.get('data_retirada') or '-')[:16].replace('T', ' ')}  \n"
                    f"**Observações:** {r.get('observacoes') or '-'}"
                )

            if st.session_state.get(f"editando_gv_{r['id']}"):
                novo_nome = st.text_input("Nome", value=r["nome"], key=f"novo_nome_gv_{r['id']}")
                novo_tel = st.text_input("Telefone", value=r["telefone"], key=f"novo_tel_gv_{r['id']}")
                nova_obs = st.text_input("Observações", value=r.get("observacoes") or "", key=f"nova_obs_gv_{r['id']}")
                if st.button("Salvar alterações", key=f"salvar_gv_{r['id']}"):
                    supabase.table("cadastros").update({"nome": novo_nome, "telefone": novo_tel, "observacoes": nova_obs}).eq("id", r["id"]).execute()
                    st.session_state[f"editando_gv_{r['id']}"] = False
                    st.rerun()


# ---------------- Vendas ----------------

def pagina_vendas():
    st.title("Vendas")

    user = st.session_state.usuario
    evento_id = selecionar_evento("Evento", "evento_vd", apenas_ativos=True)
    if not evento_id:
        return

    evento = carregar_evento(evento_id)
    produtos = carregar_produtos_evento(evento_id)

    st.subheader("Nova Venda")

    if not produtos:
        st.warning("Nenhum produto cadastrado para este evento. Cadastre em Eventos > Formulário.")
        return

    mapa_produtos = {f"{p['nome']} - {moeda(p['valor'])}": p for p in produtos}
    escolha_produto = st.selectbox("Produto", list(mapa_produtos.keys()), key="vd_produto")
    produto = mapa_produtos[escolha_produto]

    nome = st.text_input("Nome", key="vd_nome")
    telefone = st.text_input("Telefone", key="vd_telefone", placeholder="(11) 99999-9999")

    cpf = email = ""
    if evento.get("mostrar_cpf"):
        cpf = st.text_input("CPF/CNPJ" + (" *" if evento.get("cpf_obrigatorio") else " (opcional)"), key="vd_cpf")
    if evento.get("mostrar_email"):
        email = st.text_input("E-mail" + (" *" if evento.get("email_obrigatorio") else " (opcional)"), key="vd_email")

    qtd = st.number_input("Quantidade", min_value=1, step=1, value=1, key="vd_qtd")

    formas = evento.get("formas_pagamento") or []
    forma_pagamento = st.selectbox("Forma de pagamento", formas, key="vd_pagamento") if formas else None

    observacoes = st.text_input("Observações", key="vd_obs")

    valor_total = qtd * float(produto["valor"])
    st.markdown(f"**Total: {moeda(valor_total)}**")

    if st.button("Registrar Venda", type="primary"):
        if not nome or not telefone:
            st.error("Preencha nome e telefone.")
        elif evento.get("cpf_obrigatorio") and not cpf:
            st.error("CPF/CNPJ é obrigatório neste evento.")
        elif cpf and not validar_cpf_cnpj(cpf):
            st.error("CPF/CNPJ inválido.")
        elif evento.get("email_obrigatorio") and not email:
            st.error("E-mail é obrigatório neste evento.")
        elif not forma_pagamento:
            st.error("Selecione uma forma de pagamento.")
        else:
            supabase.table("vendas").insert({
                "evento_id": evento_id,
                "produto_id": produto["id"],
                "produto_nome": produto["nome"],
                "usuario_id": user["id"],
                "nome": nome,
                "telefone": telefone,
                "cpf": cpf,
                "email": email,
                "quantidade": qtd,
                "forma_pagamento": forma_pagamento,
                "valor_unitario": produto["valor"],
                "valor_total": valor_total,
                "observacoes": observacoes,
            }).execute()
            st.success("Venda registrada com sucesso!")
            st.rerun()

    st.divider()
    st.subheader("Vendas")

    col1, col2 = st.columns([1, 3])
    with col1:
        tipo_pesquisa = st.selectbox("Buscar por", ["nome", "telefone", "cpf", "produto_nome"], key="vd_tipo_pesquisa")
    with col2:
        pesquisa = st.text_input("Pesquisar", key="vd_pesquisa")

    resp = supabase.table("vendas").select("*").eq("evento_id", evento_id).order("created_at", desc=True).execute()
    registros = resp.data or []

    if pesquisa:
        p = pesquisa.lower()
        registros = [r for r in registros if p in str(r.get(tipo_pesquisa, "")).lower()]

    for r in registros:
        with st.container(border=True):
            col_info, col_acoes = st.columns([5, 1])

            with col_info:
                st.markdown(
                    f"**{r['nome']}** — {r['telefone']}  \n"
                    f"Produto: {r['produto_nome']} | Qtd: {r['quantidade']} | "
                    f"{r.get('forma_pagamento','')} | {moeda(r.get('valor_total'))}"
                )

            pode_editar = user["cargo"] == "Master" or user.get("permitir_edicao")
            pode_excluir = user["cargo"] == "Master" or user.get("permitir_exclusao")

            with col_acoes:
                with st.popover("•••", use_container_width=True):
                    if st.button("Ver detalhes", key=f"detalhes_vd_{r['id']}", use_container_width=True):
                        st.session_state[f"mostrar_detalhes_vd_{r['id']}"] = not st.session_state.get(f"mostrar_detalhes_vd_{r['id']}", False)

                    pdf_recibo = gerar_pdf_recibo(r, "venda", evento)
                    st.download_button("Recibo (PDF)", pdf_recibo, file_name=f"recibo_venda_{r['id']}.pdf", mime="application/pdf", key=f"recibo_vd_{r['id']}", use_container_width=True)

                    if pode_editar:
                        if st.button("Editar", key=f"editar_vd_{r['id']}", use_container_width=True):
                            st.session_state[f"editando_vd_{r['id']}"] = True

                    if pode_excluir:
                        if st.button("Excluir", key=f"excluir_vd_{r['id']}", use_container_width=True):
                            supabase.table("vendas").delete().eq("id", r["id"]).execute()
                            st.rerun()

            if st.session_state.get(f"mostrar_detalhes_vd_{r['id']}"):
                st.markdown(
                    f"**CPF/CNPJ:** {r.get('cpf') or '-'}  \n"
                    f"**E-mail:** {r.get('email') or '-'}  \n"
                    f"**Data da venda:** {str(r.get('created_at') or '')[:16].replace('T', ' ')}  \n"
                    f"**Observações:** {r.get('observacoes') or '-'}"
                )

            if st.session_state.get(f"editando_vd_{r['id']}"):
                novo_nome = st.text_input("Nome", value=r["nome"], key=f"novo_nome_vd_{r['id']}")
                novo_tel = st.text_input("Telefone", value=r["telefone"], key=f"novo_tel_vd_{r['id']}")
                nova_obs = st.text_input("Observações", value=r.get("observacoes") or "", key=f"nova_obs_vd_{r['id']}")
                if st.button("Salvar alterações", key=f"salvar_vd_{r['id']}"):
                    supabase.table("vendas").update({"nome": novo_nome, "telefone": novo_tel, "observacoes": nova_obs}).eq("id", r["id"]).execute()
                    st.session_state[f"editando_vd_{r['id']}"] = False
                    st.rerun()


def gerar_pdf_relatorio(df, evento, data_inicio, data_fim, tipo):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=30, bottomMargin=30)
    estilos = getSampleStyleSheet()

    elementos = []

    topo = imagem_topo_pdf(evento)
    if topo:
        elementos.append(topo)
        elementos.append(Spacer(1, 10))

    elementos.append(Paragraph(f"Relatório — {evento['nome'] if evento else ''}", estilos["Title"]))
    elementos.append(Paragraph(f"Tipo: {tipo} | Período: {data_inicio} a {data_fim}", estilos["Normal"]))
    elementos.append(Spacer(1, 10))
    elementos.append(Paragraph(f"Registros: {len(df)} | Quantidade total: {int(df['quantidade'].fillna(0).sum())} | Valor total: {moeda(df['valor_total'].fillna(0).sum())}", estilos["Normal"]))
    elementos.append(Spacer(1, 14))

    colunas = ["created_at", "tipo", "nome", "produto", "quantidade", "forma_pagamento", "valor_total", "status"]
    cabecalho = ["Data", "Tipo", "Nome", "Produto", "Qtd", "Pagamento", "Valor", "Status"]

    linhas = [cabecalho]
    for _, r in df.iterrows():
        linhas.append([
            str(r["created_at"])[:16].replace("T", " "),
            r["tipo"], r["nome"], r.get("produto") or "-", str(r["quantidade"]),
            r["forma_pagamento"] or "-", moeda(r["valor_total"]), r["status"],
        ])

    tabela = Table(linhas, repeatRows=1)
    tabela.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b2a52")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    elementos.append(tabela)

    doc.build(elementos)
    buffer.seek(0)
    return buffer


# ---------------- Relatórios ----------------

def pagina_relatorios():
    st.title("Relatórios")

    tipo = st.selectbox("Tipo", ["Todos", "Guarda-volumes", "Vendas"], key="rel_tipo")
    evento_id = selecionar_evento("Evento", "rel_evento", apenas_ativos=False)
    if not evento_id:
        return

    evento = carregar_evento(evento_id)

    col1, col2, col3 = st.columns(3)
    with col1:
        data_inicio = st.date_input("Data inicial", value=date.today(), key="rel_inicio")
    with col2:
        data_fim = st.date_input("Data final", value=date.today(), key="rel_fim")
    with col3:
        formas = evento.get("formas_pagamento") or []
        forma_filtro = st.selectbox("Pagamento", ["Todos"] + formas, key="rel_pagamento")

    status_filtro = "Todos"
    if tipo != "Vendas":
        status_filtro = st.selectbox("Status (só Guarda-volumes)", ["Todos", "Pendente", "Retirado"], key="rel_status")

    registros = []

    if tipo in ("Todos", "Guarda-volumes"):
        query = supabase.table("cadastros").select("*").eq("evento_id", evento_id)
        query = query.gte("created_at", f"{data_inicio}T00:00:00").lte("created_at", f"{data_fim}T23:59:59")
        if forma_filtro != "Todos":
            query = query.eq("forma_pagamento", forma_filtro)
        if status_filtro == "Retirado":
            query = query.eq("retirado", True)
        elif status_filtro == "Pendente":
            query = query.eq("retirado", False)
        for r in query.execute().data or []:
            registros.append({
                "tipo": "Guarda-volumes", "created_at": r.get("created_at"), "nome": r.get("nome"),
                "telefone": r.get("telefone"), "cpf": r.get("cpf"), "email": r.get("email"),
                "quantidade": r.get("quantidade_volumes"), "produto": "",
                "malas": ", ".join(normalizar_malas(r.get("numeros_malas"))),
                "forma_pagamento": r.get("forma_pagamento"), "valor_total": r.get("valor_total"),
                "status": "Retirado" if r.get("retirado") else "Pendente",
                "observacoes": r.get("observacoes"), "usuario_id": r.get("usuario_id"),
            })

    if tipo in ("Todos", "Vendas"):
        query = supabase.table("vendas").select("*").eq("evento_id", evento_id)
        query = query.gte("created_at", f"{data_inicio}T00:00:00").lte("created_at", f"{data_fim}T23:59:59")
        if forma_filtro != "Todos":
            query = query.eq("forma_pagamento", forma_filtro)
        for r in query.execute().data or []:
            registros.append({
                "tipo": "Venda", "created_at": r.get("created_at"), "nome": r.get("nome"),
                "telefone": r.get("telefone"), "cpf": r.get("cpf"), "email": r.get("email"),
                "quantidade": r.get("quantidade"), "produto": r.get("produto_nome"), "malas": "",
                "forma_pagamento": r.get("forma_pagamento"), "valor_total": r.get("valor_total"),
                "status": "-", "observacoes": r.get("observacoes"), "usuario_id": r.get("usuario_id"),
            })

    if not registros:
        st.info("Nenhum registro encontrado para os filtros selecionados.")
        return

    df = pd.DataFrame(registros).sort_values("created_at")

    st.subheader("Resumo")
    col1, col2, col3 = st.columns(3)
    col1.metric("Registros", len(df))
    col2.metric("Quantidade total", int(df["quantidade"].fillna(0).sum()))
    col3.metric("Valor total", moeda(df["valor_total"].fillna(0).sum()))

    st.markdown("**Por forma de pagamento:**")
    st.dataframe(df.groupby("forma_pagamento")["valor_total"].sum().reset_index(), use_container_width=True, hide_index=True)

    st.subheader("Prévia")
    st.dataframe(df, use_container_width=True, hide_index=True)

    csv = df.to_csv(index=False, sep=";").encode("utf-8-sig")
    st.download_button("Exportar CSV", csv, file_name=f"relatorio_{evento['nome']}_{data_inicio}_a_{data_fim}.csv", mime="text/csv")

    pdf_relatorio = gerar_pdf_relatorio(df, evento, data_inicio, data_fim, tipo)
    st.download_button("Baixar PDF", pdf_relatorio, file_name=f"relatorio_{evento['nome']}_{data_inicio}_a_{data_fim}.pdf", mime="application/pdf")

    st.divider()
    st.subheader("Fechamento de Caixa por Pessoa")

    resp_usuarios = supabase.table("usuarios").select("id, nome").execute()
    mapa_usuarios = {u["id"]: u["nome"] for u in (resp_usuarios.data or [])}
    mapa_usuarios[None] = "Master"

    df_caixa = df.copy()
    df_caixa["operador"] = df_caixa["usuario_id"].map(mapa_usuarios).fillna("Master")

    fechamento = (
        df_caixa.groupby("operador")
        .agg(registros=("nome", "count"), quantidade=("quantidade", "sum"), valor_total=("valor_total", "sum"))
        .reset_index()
        .sort_values("valor_total", ascending=False)
    )

    st.dataframe(fechamento, use_container_width=True, hide_index=True, column_config={
        "valor_total": st.column_config.NumberColumn("Valor total", format="R$ %.2f"),
    })

    csv_caixa = fechamento.to_csv(index=False, sep=";").encode("utf-8-sig")
    st.download_button("Exportar fechamento (CSV)", csv_caixa, file_name=f"fechamento_{evento['nome']}_{data_inicio}_a_{data_fim}.csv", mime="text/csv")


# ---------------- Configurações ----------------

def pagina_configuracoes():
    st.title("Configurações")

    evento_id = selecionar_evento("Evento", "cfg_evento", apenas_ativos=False)
    if not evento_id:
        return

    st.subheader("Impressora / Etiqueta deste evento")

    config = carregar_config_impressora(evento_id)

    nome_impressora = st.text_input("Nome da impressora", value=config.get("nome", "Argox"))
    largura = st.number_input("Largura da etiqueta (mm)", value=float(config.get("largura", 89)))
    altura = st.number_input("Altura da etiqueta (mm)", value=float(config.get("altura", 40)))
    margem = st.number_input("Margem interna (mm)", value=float(config.get("margem", 4)))
    fonte_mala = st.number_input("Fonte do número da mala", value=float(config.get("fonte_mala", 24)))

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Salvar Configuração", type="primary"):
            dados = {
                "evento_id": evento_id, "nome": nome_impressora, "largura": largura,
                "altura": altura, "margem": margem, "fonte_mala": fonte_mala,
            }
            existente = supabase.table("config_impressora").select("id").eq("evento_id", evento_id).execute().data
            if existente:
                supabase.table("config_impressora").update(dados).eq("evento_id", evento_id).execute()
            else:
                supabase.table("config_impressora").insert(dados).execute()
            st.success("Configuração salva para este evento.")
            st.rerun()

    with col2:
        if st.button("Usar padrão 89x40"):
            supabase.table("config_impressora").upsert({
                "evento_id": evento_id, "nome": "Argox", "largura": 89, "altura": 40, "margem": 4, "fonte_mala": 24,
            }, on_conflict="evento_id").execute()
            st.rerun()

    st.caption("A etiqueta de teste sai junto com qualquer PDF de etiqueta gerado na tela de Guarda-volumes.")


# ---------------- Trocar senha ----------------

def pagina_trocar_senha():
    st.title("Trocar senha")

    user = st.session_state.usuario

    if user["login"] == "Jess_":
        st.info("O usuário Master não troca senha por aqui.")
        return

    nova_senha = st.text_input("Nova senha", type="password")
    confirmar = st.text_input("Confirmar nova senha", type="password")

    if st.button("Salvar nova senha", type="primary"):
        if not nova_senha or nova_senha != confirmar:
            st.error("As senhas não coincidem.")
        else:
            supabase.table("usuarios").update({
                "senha": nova_senha,
                "primeiro_acesso": False,
                "alterar_senha_obrigatoria": False,
            }).eq("id", user["id"]).execute()
            st.success("Senha alterada com sucesso.")
            st.session_state.pagina = "Dashboard"
            st.rerun()


# ---------------- Main ----------------

def main():
    init_session()

    if not st.session_state.usuario:
        tela_login()
        return

    pagina = sidebar()

    paginas = {
        "Dashboard": pagina_dashboard,
        "Eventos": pagina_eventos,
        "Usuários": pagina_usuarios,
        "Guarda-volumes": pagina_guarda_volumes,
        "Vendas": pagina_vendas,
        "Relatórios": pagina_relatorios,
        "Configurações": pagina_configuracoes,
        "Trocar senha": pagina_trocar_senha,
    }

    paginas.get(pagina, pagina_dashboard)()


if __name__ == "__main__":
    main()
