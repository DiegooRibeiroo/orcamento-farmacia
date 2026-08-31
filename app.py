import streamlit as st
import pandas as pd
import xmltodict
import datetime
import urllib.parse
from fpdf import FPDF
from sqlalchemy import create_engine, text

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Sistema de Orçamentos - Farmácia", layout="wide", page_icon="💊")

# --- CONTROLE DE ACESSO ---
USUARIO_CORRETO = "admin"
SENHA_CORRETA = "farmacia123"

def verificar_login():
    if "autenticado" not in st.session_state:
        st.session_state.autenticado = False

    if not st.session_state.autenticado:
        st.markdown("<h2 style='text-align: center; color: #1E3A8A;'>🔐 Acesso Restrito - Farmácia</h2>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with st.form("login_form"):
                usuario = st.text_input("Usuário")
                senha = st.text_input("Senha", type="password")
                entrar = st.form_submit_button("Entrar no Sistema", use_container_width=True)
                
                if entrar:
                    if usuario == USUARIO_CORRETO and senha == SENHA_CORRETA:
                        st.session_state.autenticado = True
                        st.success("Login realizado com sucesso!")
                        st.rerun()
                    else:
                        st.error("Usuário ou senha incorretos.")
        return False
    return True

if not verificar_login():
    st.stop()

# --- CONEXÃO COM BANCO DE DADOS (SUPABASE / POSTGRESQL) ---
@st.cache_resource
def get_engine():
    if "DATABASE_URL" in st.secrets:
        db_url = st.secrets["DATABASE_URL"]
        return create_engine(db_url, pool_pre_ping=True)
    return None

engine = get_engine()

def init_db():
    if engine:
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS produtos (
                    id SERIAL PRIMARY KEY,
                    nome TEXT,
                    apresentacao TEXT,
                    laboratorio TEXT,
                    unidades_caixa INTEGER,
                    preco_caixa NUMERIC,
                    preco_unitario NUMERIC
                );
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS orcamentos (
                    id SERIAL PRIMARY KEY,
                    data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    cliente TEXT,
                    total NUMERIC,
                    itens_json TEXT
                );
            """))
            conn.commit()

init_db()

# --- FUNÇÕES DE PERSISTÊNCIA ---
def carregar_produtos():
    if engine:
        try:
            return pd.read_sql("SELECT * FROM produtos", engine)
        except Exception:
            pass
    return pd.DataFrame(columns=["id", "nome", "apresentacao", "laboratorio", "unidades_caixa", "preco_caixa", "preco_unitario"])

def salvar_produtos(df_novos):
    if engine and not df_novos.empty:
        df_novos.to_sql("produtos", engine, if_exists="append", index=False)

# Inicializar carrinho na sessão
if "carrinho" not in st.session_state:
    st.session_state.carrinho = []

# --- MENU SUPERIOR ---
col_logo, col_logout = st.columns([8, 2])
with col_logo:
    st.title("💊 Balcão de Orçamentos & Fracionamento")
with col_logout:
    if st.button("🚪 Sair da Conta"):
        st.session_state.autenticado = False
        st.rerun()

tab_orcamento, tab_xml, tab_catalogo = st.tabs(["📋 Novo Orçamento", "📥 Importar XML de NF-e", "📦 Catálogo de Produtos"])

# ==========================================
# ABA 1: NOVO ORÇAMENTO
# ==========================================
with tab_orcamento:
    df_prods = carregar_produtos()
    
    st.subheader("1. Selecionar Medicamento")
    
    col_busca, col_web = st.columns([3, 1])
    with col_busca:
        busca = st.text_input("🔍 Buscar no catálogo interno:", placeholder="Digite o nome do remédio...")
    
    with col_web:
        termo_web = st.text_input("🌐 Pesquisa Externa (Google):", placeholder="Ex: amoxicilina 500mg bula")
        if termo_web:
            link_pesquisa = f"https://www.google.com/search?q={urllib.parse.quote(termo_web)}"
            st.markdown(f"[🔗 Abrir pesquisa para **'{termo_web}'**]({link_pesquisa})", unsafe_allow_html=True)
            
    if not df_prods.empty:
        if busca:
            df_filtrado = df_prods[df_prods["nome"].str.contains(busca, case=False, na=False) | 
                                   df_prods["laboratorio"].str.contains(busca, case=False, na=False)]
        else:
            df_filtrado = df_prods

        if not df_filtrado.empty:
            escolha = st.selectbox(
                "Selecione o produto:",
                df_filtrado["id"].tolist(),
                format_func=lambda x: f"{df_filtrado[df_filtrado['id']==x]['nome'].values[0]} - {df_filtrado[df_filtrado['id']==x]['apresentacao'].values[0]} ({df_filtrado[df_filtrado['id']==x]['laboratorio'].values[0]})"
            )
            
            prod_sel = df_filtrado[df_filtrado["id"] == escolha].iloc[0]
            
            c1, c2, c3, c4 = st.columns(4)
            c1.info(f"**Preço Caixa:** R$ {prod_sel['preco_caixa']:.2f}")
            c2.info(f"**Unidades por Caixa:** {prod_sel['unidades_caixa']} un")
            c3.info(f"**Preço Unitário:** R$ {prod_sel['preco_unitario']:.2f}/un")
            
            tipo_venda = c4.radio("Formato de venda:", ["Caixa Fechada", "Fracionado (Unidades)"], horizontal=True)
            
            c_qtd, c_desc, c_btn = st.columns([2, 2, 2])
            with c_qtd:
                qtd = st.number_input("Quantidade:", min_value=1, value=1, step=1)
            with c_desc:
                desconto_item = st.number_input("Desconto no item (%):", min_value=0.0, max_value=100.0, value=0.0, step=1.0)
            with c_btn:
                st.write("")
                st.write("")
                if st.button("➕ Adicionar ao Orçamento", use_container_width=True):
                    if tipo_venda == "Caixa Fechada":
                        v_unit = float(prod_sel["preco_caixa"])
                        unidade_desc = "cx"
                    else:
                        v_unit = float(prod_sel["preco_unitario"])
                        unidade_desc = "un"
                    
                    subtotal = qtd * v_unit * (1 - (desconto_item / 100))
                    
                    st.session_state.carrinho.append({
                        "id": prod_sel["id"],
                        "nome": prod_sel["nome"],
                        "tipo": unidade_desc,
                        "qtd": qtd,
                        "unitario": v_unit,
                        "desconto_pct": desconto_item,
                        "subtotal": subtotal
                    })
                    st.success("Item adicionado!")
                    st.rerun()
        else:
            st.warning("Nenhum medicamento encontrado para essa busca.")
    else:
        st.info("O catálogo está vazio. Importe uma NF-e (XML) na aba ao lado.")

    # --- LISTA DO ORÇAMENTO ATUAL ---
    if st.session_state.carrinho:
        st.divider()
        st.subheader("🛒 Itens do Orçamento")
        
        df_carrinho = pd.DataFrame(st.session_state.carrinho)
        
        # Negociação em lote
        col_neg1, col_neg2 = st.columns([2, 4])
        with col_neg1:
            desc_geral = st.number_input("Aplicar Desconto Global (%):", min_value=0.0, max_value=100.0, value=0.0, step=1.0)
        
        total_bruto = sum(item["qtd"] * item["unitario"] for item in st.session_state.carrinho)
        total_liquido = total_bruto * (1 - (desc_geral / 100))
        
        st.dataframe(
            df_carrinho.rename(columns={
                "nome": "Produto", "tipo": "Tipo", "qtd": "Qtd",
                "unitario": "Valor Unit.", "desconto_pct": "Desc %", "subtotal": "Subtotal (R$)"
            }),
            use_container_width=True
        )
        
        st.markdown(f"### Total Final: **R$ {total_liquido:.2f}**")
        
        col_c1, col_c2, col_c3 = st.columns([2, 2, 2])
        with col_c1:
            if st.button("🗑️ Limpar Orçamento", use_container_width=True):
                st.session_state.carrinho = []
                st.rerun()
                
        with col_c2:
            nome_cliente = st.text_input("Nome do Cliente:", value="Cliente Balcão")
            tel_cliente = st.text_input("WhatsApp (ex: 5585999999999):", value="")
            
        with col_c3:
            st.write("")
            st.write("")
            if tel_cliente:
                msg = f"Olá {nome_cliente}! Segue seu orçamento da Farmácia:\n\n"
                for item in st.session_state.carrinho:
                    msg += f"• {item['nome']} ({item['qtd']} {item['tipo']}) - R$ {item['subtotal']:.2f}\n"
                msg += f"\n*Total: R$ {total_liquido:.2f}*"
                link_zap = f"https://wa.me/{tel_cliente}?text={urllib.parse.quote(msg)}"
                st.markdown(f"<a href='{link_zap}' target='_blank' style='display:inline-block;padding:10px 20px;background-color:#25D366;color:white;text-decoration:none;border-radius:6px;font-weight:bold;text-align:center;width:100%;'>📲 Enviar no WhatsApp</a>", unsafe_allow_html=True)

# ==========================================
# ABA 2: IMPORTAR XML
# ==========================================
with tab_xml:
    st.subheader("📥 Importação de NF-e (XML)")
    st.write("Suba o arquivo XML fornecido pela distribuidora para cadastrar os produtos automaticamente.")
    
    xml_file = st.file_uploader("Selecione o arquivo .xml da NF-e", type=["xml"])
    
    if xml_file:
        try:
            doc = xmltodict.parse(xml_file.read())
            nfe = doc.get("nfeProc", doc).get("NFe", {}).get("infNFe", {})
            detalhes = nfe.get("det", [])
            if isinstance(detalhes, dict):
                detalhes = [detalhes]
                
            produtos_importados = []
            for item in detalhes:
                prod = item.get("prod", {})
                nome = prod.get("xProd", "Não identificado")
                v_un = float(prod.get("vUnCom", 0.0))
                
                produtos_importados.append({
                    "nome": nome,
                    "apresentacao": prod.get("uCom", "CX"),
                    "laboratorio": "Distribuidora",
                    "unidades_caixa": 1,
                    "preco_caixa": v_un,
                    "preco_unitario": v_un
                })
                
            df_novos = pd.DataFrame(produtos_importados)
            st.dataframe(df_novos, use_container_width=True)
            
            if st.button("💾 Gravar Produtos no Banco de Dados", use_container_width=True):
                salvar_produtos(df_novos)
                st.success("Medicamentos cadastrados com sucesso no Supabase!")
                st.rerun()
                
        except Exception as e:
            st.error(f"Erro ao processar o XML: {e}")

# ==========================================
# ABA 3: CATÁLOGO
# ==========================================
with tab_catalogo:
    st.subheader("📦 Catálogo Geral de Produtos")
    df_todos = carregar_produtos()
    if not df_todos.empty:
        st.dataframe(df_todos, use_container_width=True)
    else:
        st.info("Nenhum produto cadastrado até o momento.")
