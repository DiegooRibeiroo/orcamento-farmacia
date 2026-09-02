import streamlit as st
import pandas as pd
import xmltodict
import json
from datetime import datetime
import urllib.parse
import re
from fpdf import FPDF
from sqlalchemy import create_engine, text
from supabase import create_client, Client

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Preço na Mão - Sistema Comercial de Cotações",
    layout="wide",
    page_icon="🏷️"
)

# --- CLIENTES DE BANCO E AUTENTICAÇÃO ---
@st.cache_resource
def get_engine():
    if "DATABASE_URL" in st.secrets:
        return create_engine(st.secrets["DATABASE_URL"], pool_pre_ping=True, pool_size=5, max_overflow=10)
    return None

@st.cache_resource
def get_supabase_client() -> Client:
    url = st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY")
    if url and key:
        return create_client(url, key)
    return None

engine = get_engine()
supabase = get_supabase_client()

# --- FUNÇÕES AUXILIARES DE USUÁRIO / EMAIL ---
def validar_formato_email(email: str) -> bool:
    padrao = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return bool(re.match(padrao, email.strip()))

def obter_email_por_identificador(identificador: str) -> str:
    ident = identificador.strip().lower()
    if "@" in ident:
        return ident
    # Buscar e-mail associado ao username no banco
    if engine:
        try:
            with engine.connect() as conn:
                res = conn.execute(
                    text("SELECT email FROM perfis_usuarios WHERE LOWER(username) = :u"),
                    {"u": ident}
                ).fetchone()
                if res:
                    return res[0]
        except Exception:
            pass
    return ident

def usuario_ja_existe(username: str) -> bool:
    if engine:
        try:
            with engine.connect() as conn:
                res = conn.execute(
                    text("SELECT 1 FROM perfis_usuarios WHERE LOWER(username) = :u"),
                    {"u": username.strip().lower()}
                ).fetchone()
                return res is not None
        except Exception:
            pass
    return False

def vincular_perfil(user_id: str, username: str, email: str):
    if engine:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("INSERT INTO perfis_usuarios (id, username, email) VALUES (:id, :u, :e) ON CONFLICT DO NOTHING"),
                    {"id": user_id, "u": username.strip().lower(), "e": email.strip().lower()}
                )
        except Exception:
            pass

# --- CONTROLE DE AUTENTICAÇÃO HÍBRIDO ---
def autenticar_usuario():
    if "autenticado" not in st.session_state:
        st.session_state.autenticado = False
        st.session_state.usuario_logado = ""
        st.session_state.usuario_email = ""

    if st.session_state.autenticado:
        return True

    st.markdown("<h2 style='text-align: center; color: #1E3A8A;'>🏷️ Preço na Mão</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #64748B;'>Acesse com sua conta ou registre-se para utilizar o sistema.</p>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        tab_login, tab_cadastro, tab_recuperar = st.tabs(["🔑 Entrar", "✨ Criar Conta", "✉️ Esqueci a Senha"])

        # 1. ABA DE LOGIN (E-mail ou Usuário)
        with tab_login:
            with st.form("form_login"):
                login_id = st.text_input("Usuário ou E-mail")
                senha = st.text_input("Senha", type="password")
                btn_entrar = st.form_submit_button("Acessar Plataforma", use_container_width=True)

                if btn_entrar:
                    if not login_id or not senha:
                        st.warning("Preencha todos os campos.")
                    else:
                        email_final = obter_email_por_identificador(login_id)
                        try:
                            res = supabase.auth.sign_in_with_password({"email": email_final, "password": senha})
                            st.session_state.autenticado = True
                            st.session_state.usuario_email = res.user.email
                            st.session_state.usuario_logado = login_id.strip()
                            st.success("Acesso autorizado!")
                            st.rerun()
                        except Exception:
                            st.error("Usuário/E-mail ou senha incorretos. Verifique suas credenciais.")

        # 2. ABA DE NOVO CADASTRO
        with tab_cadastro:
            with st.form("form_cadastro"):
                novo_username = st.text_input("Nome de Usuário (Apelido para login)")
                novo_email = st.text_input("Seu E-mail Válido (para confirmação e recuperação)")
                nova_senha = st.text_input("Crie uma Senha (mínimo 6 dígitos)", type="password")
                confirma_senha = st.text_input("Confirme a Senha", type="password")
                btn_cadastrar = st.form_submit_button("Criar Minha Conta", use_container_width=True)

                if btn_cadastrar:
                    novo_username = novo_username.strip().lower()
                    novo_email = novo_email.strip().lower()

                    if not novo_username or not novo_email or not nova_senha:
                        st.warning("Preencha todos os campos obrigatórios.")
                    elif len(novo_username) < 3:
                        st.error("O nome de usuário deve ter no mínimo 3 caracteres.")
                    elif not validar_formato_email(novo_email):
                        st.error("Por favor, digite um formato de e-mail válido (ex: seuemail@dominio.com).")
                    elif len(nova_senha) < 6:
                        st.error("A senha deve conter no mínimo 6 caracteres.")
                    elif nova_senha != confirma_senha:
                        st.error("As senhas digitadas não coincidem.")
                    elif usuario_ja_existe(novo_username):
                        st.error(f"O nome de usuário '{novo_username}' já está em uso. Por favor, escolha outro.")
                    else:
                        try:
                            # Criação nativa no Supabase Auth com metadados
                            res = supabase.auth.sign_up({
                                "email": novo_email,
                                "password": nova_senha,
                                "options": {
                                    "data": {"username": novo_username}
                                }
                            })
                            if res.user:
                                vincular_perfil(res.user.id, novo_username, novo_email)
                            st.success("✅ Conta criada com sucesso! Verifique seu e-mail para confirmar a ativação.")
                        except Exception as e:
                            msg_erro = str(e)
                            if "already registered" in msg_erro.lower() or "unique" in msg_erro.lower():
                                st.error("Este e-mail já possui cadastro no sistema. Tente fazer login ou recuperar a senha.")
                            else:
                                st.error(f"Erro ao criar conta: {msg_erro}")

        # 3. ABA DE RECUPERAÇÃO DE SENHA
        with tab_recuperar:
            with st.form("form_recuperar"):
                st.caption("Digite seu e-mail cadastrado ou seu nome de usuário para enviarmos as instruções.")
                rec_id = st.text_input("E-mail ou Usuário Cadastrado")
                btn_rec = st.form_submit_button("Enviar Link de Recuperação", use_container_width=True)

                if btn_rec:
                    if not rec_id:
                        st.warning("Por favor, preencha este campo.")
                    else:
                        email_recuperacao = obter_email_por_identificador(rec_id)
                        if not validar_formato_email(email_recuperacao):
                            st.error("Não localizamos um e-mail válido associado a este usuário.")
                        else:
                            try:
                                supabase.auth.reset_password_for_email(email_recuperacao)
                                st.success(f"Link de redefinição enviado para o e-mail cadastrado!")
                            except Exception as e:
                                st.error(f"Erro ao solicitar link: {e}")

    return False

if not autenticar_usuario():
    st.stop()

# --- FUNÇÕES DE BANCO DE DADOS (POSTGRESQL) ---
@st.cache_data(ttl=600)
def carregar_produtos():
    if engine:
        try:
            return pd.read_sql("SELECT * FROM produtos ORDER BY nome ASC", engine)
        except Exception:
            pass
    return pd.DataFrame(columns=["id", "nome", "apresentacao", "laboratorio", "unidades_caixa", "preco_caixa", "preco_unitario"])

@st.cache_data(ttl=600)
def carregar_clientes():
    if engine:
        try:
            return pd.read_sql("SELECT * FROM clientes ORDER BY nome ASC", engine)
        except Exception:
            pass
    return pd.DataFrame(columns=["id", "nome", "telefone", "documento"])

@st.cache_data(ttl=300)
def carregar_orcamentos():
    if engine:
        try:
            return pd.read_sql("SELECT * FROM orcamentos ORDER BY criado_em DESC", engine)
        except Exception:
            pass
    return pd.DataFrame(columns=["id", "cliente_nome", "cliente_telefone", "total", "desconto_global", "itens", "observacoes", "status", "criado_em"])

def salvar_produtos(df_novos):
    if engine and not df_novos.empty:
        df_novos.to_sql("produtos", engine, if_exists="append", index=False)
        st.cache_data.clear()

def salvar_cliente_db(nome, tel, doc):
    if engine and nome.strip():
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO clientes (nome, telefone, documento) VALUES (:nome, :tel, :doc)"),
                {"nome": nome.strip(), "tel": tel.strip(), "doc": doc.strip()}
            )
        st.cache_data.clear()

def salvar_orcamento_db(cliente_nome, cliente_tel, total, desc_global, itens, obs):
    if engine and itens:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO orcamentos (cliente_nome, cliente_telefone, total, desconto_global, itens, observacoes) 
                    VALUES (:cliente, :tel, :total, :desc, :itens, :obs)
                """),
                {
                    "cliente": cliente_nome,
                    "tel": cliente_tel,
                    "total": total,
                    "desc": desc_global,
                    "itens": json.dumps(itens),
                    "obs": obs
                }
            )
        st.cache_data.clear()

def atualizar_status_orcamento(orc_id, novo_status):
    if engine:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE orcamentos SET status = :status WHERE id = :id"),
                {"status": novo_status, "id": orc_id}
            )
        st.cache_data.clear()

# --- ESTADOS DA SESSÃO ---
if "carrinho" not in st.session_state:
    st.session_state.carrinho = []

if "ultimo_adicionado" not in st.session_state:
    st.session_state.ultimo_adicionado = None

df_prods = carregar_produtos()
df_clientes = carregar_clientes()

# --- GERADOR DE PDF ---
class PDFOrcamento(FPDF):
    def __init__(self, emp_nome, emp_cnpj, emp_tel):
        super().__init__()
        self.emp_nome = emp_nome
        self.emp_cnpj = emp_cnpj
        self.emp_tel = emp_tel

    def header(self):
        self.set_font('helvetica', 'B', 15)
        self.set_text_color(30, 58, 138)
        self.cell(0, 7, self.emp_nome.upper(), align='C')
        self.ln(6)
        self.set_font('helvetica', '', 9)
        self.set_text_color(90, 90, 90)
        self.cell(0, 5, f"CNPJ/Doc: {self.emp_cnpj} | Contato: {self.emp_tel}", align='C')
        self.ln(5)
        self.set_font('helvetica', 'B', 11)
        self.set_text_color(50, 50, 50)
        self.cell(0, 6, "PROPOSTA COMERCIAL & COTAÇÃO", align='C')
        self.ln(7)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f'Página {self.page_no()} | Emitido via Preço na Mão em {datetime.now().strftime("%d/%m/%Y %H:%M")}', align='C')

# --- CABEÇALHO SUPERIOR ---
col_logo, col_logout = st.columns([8, 2])
with col_logo:
    st.title("🏷️ Preço na Mão - Cotações & Vendas")
with col_logout:
    if st.button("🚪 Sair da Conta"):
        supabase.auth.sign_out()
        st.session_state.autenticado = False
        st.session_state.usuario_logado = ""
        st.session_state.usuario_email = ""
        st.session_state.carrinho = []
        st.session_state.ultimo_adicionado = None
        st.rerun()

# --- BARRA LATERAL ---
with st.sidebar:
    st.markdown(f"👤 Conectado como:\n**{st.session_state.usuario_logado or st.session_state.usuario_email}**")
    if st.button("🚪 Sair / Desconectar", key="btn_sair_side"):
        supabase.auth.sign_out()
        st.session_state.autenticado = False
        st.session_state.usuario_logado = ""
        st.session_state.usuario_email = ""
        st.session_state.carrinho = []
        st.session_state.ultimo_adicionado = None
        st.rerun()

    st.divider()
    with st.expander("🏢 Dados da Sua Empresa (Cabeçalho/PDF)"):
        emp_nome = st.text_input("Razão Social / Nome Fantasia", value="Minha Loja & Distribuição")
        emp_cnpj = st.text_input("CNPJ / CPF", value="00.000.000/0001-00")
        emp_tel = st.text_input("Telefone de Contato", value="(00) 00000-0000")

    st.divider()
    st.subheader("📥 Importação de Notas (XML)")
    xml_files = st.file_uploader("Upload de arquivos XML (NF-e)", type=["xml"], accept_multiple_files=True)
    
    if xml_files and st.button("Processar e Salvar no Catálogo", use_container_width=True):
        produtos_importados = []
        for xml_file in xml_files:
            try:
                doc = xmltodict.parse(xml_file.read())
                nfe = doc.get("nfeProc", doc).get("NFe", {}).get("infNFe", {})
                detalhes = nfe.get("det", [])
                emit = nfe.get("emit", {}).get("xNome", "Fornecedor")
                if isinstance(detalhes, dict):
                    detalhes = [detalhes]
                    
                for item in detalhes:
                    prod = item.get("prod", {})
                    nome = prod.get("xProd", "Item não identificado")
                    v_un = float(prod.get("vUnCom", 0.0))
                    u_com = str(prod.get("uCom", "UN")).strip().upper()
                    
                    produtos_importados.append({
                        "nome": nome,
                        "apresentacao": u_com,
                        "laboratorio": emit[:35],
                        "unidades_caixa": 1,
                        "preco_caixa": v_un,
                        "preco_unitario": v_un
                    })
            except Exception as e:
                st.error(f"Erro no arquivo {xml_file.name}: {e}")
                
        if produtos_importados:
            df_novos = pd.DataFrame(produtos_importados)
            salvar_produtos(df_novos)
            st.success(f"✅ {len(df_novos)} produtos importados com sucesso!")
            st.rerun()

    st.divider()
    with st.expander("✍️ Cadastrar Produto Manual no Catálogo"):
        with st.form("form_manual_banco"):
            m_nome = st.text_input("Nome / Descrição do Produto")
            m_apres = st.selectbox("Unidade / Embalagem:", ["UN", "CX", "PCT", "KG", "M", "FARDO", "PAR", "KIT"])
            m_lab = st.text_input("Marca / Fornecedor / Fabricante", value="Geral")
            m_un = st.number_input("Itens por Embalagem Fechada", min_value=1, value=1)
            m_preco_cx = st.number_input("Preço de Custo Total (R$)", min_value=0.01, value=10.0, step=0.5)
            
            if st.form_submit_button("Salvar no Catálogo"):
                df_manual = pd.DataFrame([{
                    "nome": m_nome,
                    "apresentacao": m_apres,
                    "laboratorio": m_lab,
                    "unidades_caixa": m_un,
                    "preco_caixa": m_preco_cx,
                    "preco_unitario": m_preco_cx / m_un
                }])
                salvar_produtos(df_manual)
                st.success("Produto cadastrado com sucesso!")
                st.rerun()

    st.divider()
    with st.expander("🛠️ Manutenção & Backup"):
        if not df_prods.empty:
            csv = df_prods.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Baixar Catálogo (CSV)",
                data=csv,
                file_name=f"catalogo_backup_{datetime.now().strftime('%d%m%Y')}.csv",
                mime="text/csv",
                use_container_width=True
            )
            
        if st.button("🔄 Atualizar Cache Geral", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        if st.button("🧹 Remover Itens Duplicados", use_container_width=True):
            if engine:
                try:
                    with engine.begin() as conn:
                        conn.execute(text("""
                            DELETE FROM produtos
                            WHERE id NOT IN (
                                SELECT MIN(id)
                                FROM produtos
                                GROUP BY nome, apresentacao, laboratorio
                            );
                        """))
                    st.cache_data.clear()
                    st.success("Duplicados removidos!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro: {e}")

# --- ABAS PRINCIPAIS ---
tab_orcamento, tab_historico, tab_clientes, tab_catalogo = st.tabs([
    "📋 Nova Cotação", 
    "📜 Histórico de Orçamentos", 
    "👥 Clientes Cadastrados", 
    "📦 Catálogo Geral"
])

# ==========================================
# 1. ABA DE COTAÇÃO & ORÇAMENTO
# ==========================================
with tab_orcamento:
    if st.session_state.ultimo_adicionado:
        st.success(f"✅ **Item adicionado:** {st.session_state.ultimo_adicionado}")

    st.subheader("1. Selecionar ou Adicionar Item")

    origem = st.radio(
        "Origem do Item:",
        ["📦 Buscar no Catálogo / NF-e", "✍️ Digitar Item Avulso / Manual"],
        horizontal=True
    )

    with st.expander("🌐 Pesquisa Rápida na Web (Preços de Mercado / Especificações)"):
        c_pesq1, c_pesq2 = st.columns([3, 1])
        with c_pesq1:
            termo_pesquisa = st.text_input("Pesquisar produto na internet:", placeholder="Ex: especificação técnica, modelo ou preço...")
        with c_pesq2:
            st.write("")
            st.write("")
            if termo_pesquisa:
                link_google = f"https://www.google.com/search?q={urllib.parse.quote(termo_pesquisa)}"
                st.markdown(f"[🔍 Abrir Pesquisa no Google]({link_google})", unsafe_allow_html=True)

    st.divider()

    # --- ITEM DO CATÁLOGO ---
    if origem == "📦 Buscar no Catálogo / NF-e":
        if not df_prods.empty:
            c_f1, c_f2 = st.columns([3, 1])
            with c_f1:
                busca_filtro = st.text_input("🔍 Digite para filtrar no catálogo:", placeholder="Nome do produto ou fornecedor...")
            with c_f2:
                margem_padrao = st.number_input("Margem / Lucro Padrão (%):", min_value=0.0, value=30.0, step=5.0)

            if busca_filtro:
                df_filtrado = df_prods[df_prods["nome"].str.contains(busca_filtro, case=False, na=False) |
                                       df_prods["laboratorio"].str.contains(busca_filtro, case=False, na=False)]
            else:
                df_filtrado = df_prods

            if not df_filtrado.empty:
                escolha_id = st.selectbox(
                    "Selecione o produto:",
                    df_filtrado["id"].tolist(),
                    format_func=lambda x: f"{df_filtrado[df_filtrado['id']==x]['nome'].values[0]} | Fornec: {df_filtrado[df_filtrado['id']==x]['laboratorio'].values[0]} | Custo: R$ {float(df_filtrado[df_filtrado['id']==x]['preco_caixa'].values[0]):.2f}"
                )
                
                prod_selecionado = df_filtrado[df_filtrado["id"] == escolha_id].iloc[0]

                custo_cx = float(prod_selecionado["preco_caixa"])
                un_cx = int(prod_selecionado["unidades_caixa"])
                custo_un = float(prod_selecionado["preco_unitario"])
                u_medida = prod_selecionado["apresentacao"]

                c_info1, c_info2, c_info3, c_info4 = st.columns(4)
                c_info1.info(f"**Custo Embalagem ({u_medida}):** R$ {custo_cx:.2f}")
                c_info2.info(f"**Itens p/ Embalagem:** {un_cx} un")
                c_info3.info(f"**Custo Unitário:** R$ {custo_un:.2f}")
                formato_venda = c_info4.radio("Formato de Venda:", [f"Embalagem Fechada ({u_medida})", "Fracionado (Unitário)"], horizontal=True)

                col_qtd, col_margem, col_desc, col_btn = st.columns([2, 2, 2, 2])
                with col_qtd:
                    qtd_venda = st.number_input("Quantidade:", min_value=1, value=1, step=1, key="qtd_db")
                with col_margem:
                    margem_item = st.number_input("Margem de Lucro (%):", min_value=0.0, value=margem_padrao, step=5.0, key="margem_db")
                with col_desc:
                    desconto_item = st.number_input("Desconto no Item (%):", min_value=0.0, max_value=100.0, value=0.0, step=1.0, key="desc_db")

                base_custo = custo_cx if "Fechada" in formato_venda else custo_un
                preco_venda_unitario = base_custo * (1 + (margem_item / 100))
                subtotal_sem_desc = qtd_venda * preco_venda_unitario
                subtotal_final_item = subtotal_sem_desc * (1 - (desconto_item / 100))

                col_calc1, col_calc2 = st.columns(2)
                with col_calc1:
                    st.markdown(f"**Preço Unitário de Venda:** R\\$ {preco_venda_unitario:.2f}")
                with col_calc2:
                    st.markdown(f"**Subtotal do Item:** :green[**R\\$ {subtotal_final_item:.2f}**]")

                with col_btn:
                    st.write("")
                    st.write("")
                    if st.button("➕ Adicionar à Cotação", use_container_width=True, key="btn_add_db"):
                        unidade_label = u_medida if "Fechada" in formato_venda else "un"
                        st.session_state.carrinho.append({
                            "nome": prod_selecionado["nome"],
                            "tipo": unidade_label,
                            "qtd": qtd_venda,
                            "custo": base_custo,
                            "margem": margem_item,
                            "unitario": preco_venda_unitario,
                            "desconto_pct": desconto_item,
                            "subtotal": subtotal_final_item
                        })
                        st.session_state.ultimo_adicionado = f"{qtd_venda}x {prod_selecionado['nome']} ({unidade_label}) - R$ {subtotal_final_item:.2f}"
                        st.toast(f"✅ Adicionado: {prod_selecionado['nome']}", icon="🛒")
                        st.rerun()
            else:
                st.warning("Nenhum produto encontrado.")
        else:
            st.info("Nenhum produto cadastrado no catálogo.")

    # --- ITEM AVULSO / MANUAL ---
    else:
        with st.container():
            col_av1, col_av2, col_av3 = st.columns([3, 2, 1])
            with col_av1:
                av_nome = st.text_input("Descrição do Item / Produto Avulso:")
            with col_av2:
                av_tipo = st.selectbox("Unidade de Medida:", ["UN", "CX", "PCT", "M", "KG", "PAR", "KIT"])
            with col_av3:
                av_qtd = st.number_input("Quantidade:", min_value=1, value=1, step=1, key="av_qtd")

            col_av4, col_av5, col_av6 = st.columns([2, 2, 2])
            with col_av4:
                av_valor_unit = st.number_input("Preço Unitário de Venda (R$):", min_value=0.01, value=25.0, step=0.5)
            with col_av5:
                av_desc = st.number_input("Desconto no Item (%):", min_value=0.0, max_value=100.0, value=0.0, step=1.0, key="av_desc")
            
            salvar_no_catalogo = st.checkbox("💾 Salvar também este produto no Catálogo Geral permanente", value=True)
            av_subtotal = (av_qtd * av_valor_unit) * (1 - (av_desc / 100))

            with col_av6:
                st.write("")
                st.write("")
                if st.button("➕ Adicionar Item Avulso", use_container_width=True, key="btn_add_avulso"):
                    if av_nome.strip():
                        st.session_state.carrinho.append({
                            "nome": av_nome.strip(),
                            "tipo": av_tipo,
                            "qtd": av_qtd,
                            "custo": 0.0,
                            "margem": 0.0,
                            "unitario": av_valor_unit,
                            "desconto_pct": av_desc,
                            "subtotal": av_subtotal
                        })
                        
                        if salvar_no_catalogo:
                            df_novo_avulso = pd.DataFrame([{
                                "nome": av_nome.strip(),
                                "apresentacao": av_tipo,
                                "laboratorio": "Cadastro Manual",
                                "unidades_caixa": 1,
                                "preco_caixa": av_valor_unit,
                                "preco_unitario": av_valor_unit
                            }])
                            salvar_produtos(df_novo_avulso)

                        st.session_state.ultimo_adicionado = f"{av_qtd}x {av_nome} - R$ {av_subtotal:.2f}"
                        st.toast(f"✅ Adicionado: {av_nome}", icon="🛒")
                        st.rerun()
                    else:
                        st.error("Por favor, preencha o nome do item.")

    # --- FECHAMENTO DO ORÇAMENTO ---
    if st.session_state.carrinho:
        st.divider()
        st.subheader("🛒 Itens da Cotação")

        df_carrinho = pd.DataFrame(st.session_state.carrinho)

        col_g1, col_g2 = st.columns([2, 4])
        with col_g1:
            desc_geral = st.number_input("Desconto Global no Total (%):", min_value=0.0, max_value=100.0, value=0.0, step=1.0)

        total_bruto = sum(item["qtd"] * item["unitario"] for item in st.session_state.carrinho)
        total_com_desc_itens = sum(item["subtotal"] for item in st.session_state.carrinho)
        total_liquido = total_com_desc_itens * (1 - (desc_geral / 100))

        st.dataframe(
            df_carrinho.rename(columns={
                "nome": "Item", "tipo": "Un.", "qtd": "Qtd",
                "unitario": "Preço Unit. (R$)", "desconto_pct": "Desc %", "subtotal": "Subtotal (R$)"
            })[["Item", "Un.", "Qtd", "Preço Unit. (R$)", "Desc %", "Subtotal (R$)"]],
            use_container_width=True
        )

        st.markdown(f"### Total da Proposta: :green[**R\\$ {total_liquido:.2f}**]")

        st.divider()
        st.subheader("2. Identificação do Cliente & Finalização")
        
        col_cli_sel, col_cli_nome, col_cli_tel = st.columns([2, 2, 2])
        with col_cli_sel:
            opcoes_clientes = ["-- Digitar Novo / Balcão --"] + df_clientes["nome"].tolist()
            cliente_escolhido = st.selectbox("Buscar Cliente Cadastrado:", opcoes_clientes)

        nome_sugestao = "Cliente Balcão"
        tel_sugestao = ""
        if cliente_escolhido != "-- Digitar Novo / Balcão --":
            cli_row = df_clientes[df_clientes["nome"] == cliente_escolhido].iloc[0]
            nome_sugestao = cli_row["nome"]
            tel_sugestao = str(cli_row["telefone"] or "")

        with col_cli_nome:
            nome_cliente = st.text_input("Nome do Cliente / Razão Social:", value=nome_sugestao)
        with col_cli_tel:
            tel_cliente = st.text_input("WhatsApp (ex: 5585999999999):", value=tel_sugestao)

        obs_orcamento = st.text_input("Condições / Prazos de Entrega:", value="Validade da proposta: 3 dias úteis.")

        # --- AÇÕES FINAIS ---
        col_act1, col_act2, col_act3, col_act4 = st.columns(4)
        
        with col_act1:
            if st.button("💾 Salvar Cotação no Histórico", type="primary", use_container_width=True):
                salvar_orcamento_db(nome_cliente, tel_cliente, total_liquido, desc_geral, st.session_state.carrinho, obs_orcamento)
                st.success("✅ Orçamento salvo com sucesso!")
                st.rerun()

        with col_act2:
            if tel_cliente.strip():
                msg = f"Olá *{nome_cliente}*! Segue a cotação de *{emp_nome}* via Preço na Mão:\n\n"
                for item in st.session_state.carrinho:
                    msg += f"• *{item['nome']}* ({item['qtd']} {item['tipo']}) - R$ {item['subtotal']:.2f}\n"
                if desc_geral > 0:
                    msg += f"\n*Desconto Comercial:* {desc_geral}%\n"
                msg += f"\n💰 *Total da Proposta: R$ {total_liquido:.2f}*\n\n_{obs_orcamento}_"
                link_zap = f"https://wa.me/{tel_cliente.strip()}?text={urllib.parse.quote(msg)}"
                st.markdown(f"<a href='{link_zap}' target='_blank' style='display:inline-block;padding:10px 10px;background-color:#25D366;color:white;text-decoration:none;border-radius:6px;font-weight:bold;text-align:center;width:100%;'>📲 WhatsApp</a>", unsafe_allow_html=True)
            else:
                st.caption("Preencha o WhatsApp.")

        with col_act3:
            try:
                pdf = PDFOrcamento(emp_nome, emp_cnpj, emp_tel)
                pdf.add_page()
                pdf.set_font('helvetica', '', 10)
                pdf.cell(0, 6, f"Cliente: {nome_cliente}", ln=True)
                pdf.cell(0, 6, f"Telefone: {tel_cliente} | Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True)
                pdf.cell(0, 6, f"Condicoes: {obs_orcamento}", ln=True)
                pdf.ln(4)

                pdf.set_fill_color(240, 240, 240)
                pdf.set_font('helvetica', 'B', 9)
                pdf.cell(90, 7, "Item / Descricao", border=1, fill=True)
                pdf.cell(20, 7, "Un.", border=1, align='C', fill=True)
                pdf.cell(20, 7, "Qtd", border=1, align='C', fill=True)
                pdf.cell(30, 7, "Unitario", border=1, align='R', fill=True)
                pdf.cell(30, 7, "Subtotal", border=1, align='R', fill=True)
                pdf.ln(7)

                pdf.set_font('helvetica', '', 8)
                for it in st.session_state.carrinho:
                    nome_rec = it['nome'][:45]
                    pdf.cell(90, 6, nome_rec, border=1)
                    pdf.cell(20, 6, str(it['tipo']), border=1, align='C')
                    pdf.cell(20, 6, str(it['qtd']), border=1, align='C')
                    pdf.cell(30, 6, f"R$ {it['unitario']:.2f}", border=1, align='R')
                    pdf.cell(30, 6, f"R$ {it['subtotal']:.2f}", border=1, align='R')
                    pdf.ln(6)

                pdf.ln(4)
                pdf.set_font('helvetica', 'B', 11)
                pdf.cell(0, 7, f"TOTAL: R$ {total_liquido:.2f}", align='R', ln=True)

                pdf_bytes = bytes(pdf.output())
                st.download_button(
                    label="📄 Baixar PDF",
                    data=pdf_bytes,
                    file_name=f"proposta_{datetime.now().strftime('%d%m%Y_%H%M')}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Erro no PDF: {e}")

        with col_act4:
            if st.button("🗑️ Limpar Carrinho", use_container_width=True):
                st.session_state.carrinho = []
                st.session_state.ultimo_adicionado = None
                st.rerun()

# ==========================================
# 2. ABA DE HISTÓRICO DE ORÇAMENTOS
# ==========================================
with tab_historico:
    st.subheader("📜 Histórico de Propostas & Cotações Salvas")
    df_orc = carregar_orcamentos()
    
    if not df_orc.empty:
        for idx, row in df_orc.iterrows():
            with st.expander(f"📌 Orçamento #{row['id']} - {row['cliente_nome']} | R$ {float(row['total']):.2f} [{row['status']}]"):
                c_h1, c_h2, c_h3 = st.columns([3, 2, 2])
                c_h1.write(f"**Data:** {pd.to_datetime(row['criado_em']).strftime('%d/%m/%Y %H:%M')}")
                c_h2.write(f"**Telefone:** {row['cliente_telefone']}")
                c_h3.write(f"**Desconto Global:** {row['desconto_global']}%")
                st.write(f"**Obs:** {row['observacoes']}")
                
                try:
                    itens_list = json.loads(row['itens']) if isinstance(row['itens'], str) else row['itens']
                    st.dataframe(pd.DataFrame(itens_list)[["nome", "tipo", "qtd", "unitario", "subtotal"]], use_container_width=True)
                except Exception:
                    st.write(row['itens'])
                    
                col_st1, col_st2 = st.columns([2, 4])
                with col_st1:
                    novo_st = st.selectbox("Atualizar Status:", ["Pendente", "Aprovado", "Faturado", "Cancelado"], index=["Pendente", "Aprovado", "Faturado", "Cancelado"].index(row['status']) if row['status'] in ["Pendente", "Aprovado", "Faturado", "Cancelado"] else 0, key=f"st_{row['id']}")
                    if st.button("Salvar Status", key=f"btn_st_{row['id']}"):
                        atualizar_status_orcamento(row['id'], novo_st)
                        st.success("Status atualizado!")
                        st.rerun()
    else:
        st.info("Nenhum orçamento salvo no histórico até o momento.")

# ==========================================
# 3. ABA DE CADASTRO DE CLIENTES
# ==========================================
with tab_clientes:
    st.subheader("👥 Gestão & Cadastro de Clientes")
    
    with st.expander("➕ Cadastrar Novo Cliente"):
        with st.form("form_novo_cli"):
            c_n = st.text_input("Nome Completo / Razão Social")
            c_t = st.text_input("WhatsApp / Telefone (com DDD)")
            c_d = st.text_input("CPF / CNPJ")
            if st.form_submit_button("Salvar Cliente"):
                salvar_cliente_db(c_n, c_t, c_d)
                st.success("Cliente salvo com sucesso!")
                st.rerun()

    if not df_clientes.empty:
        st.dataframe(df_clientes[["id", "nome", "telefone", "documento"]], use_container_width=True)
    else:
        st.info("Nenhum cliente cadastrado ainda.")

# ==========================================
# 4. ABA DE CATÁLOGO GERAL
# ==========================================
with tab_catalogo:
    st.subheader("📦 Catálogo Geral de Produtos & Preços (Supabase)")
    if not df_prods.empty:
        st.dataframe(df_prods, use_container_width=True)
    else:
        st.info("Nenhum item cadastrado no banco de dados.")
