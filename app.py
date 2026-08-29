import streamlit as st
import sqlite3
import pandas as pd
import xmltodict
from fpdf import FPDF
from datetime import datetime
import io

# Configuração da Página
st.set_page_config(page_title="Gestão & Orçamentos - Farmácia", layout="wide", page_icon="💊")

# Conexão com o Banco SQLite
def get_db_connection():
    conn = sqlite3.connect('farmacia.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT,
            nome TEXT,
            fornecedor TEXT,
            ncm TEXT,
            custo_unitario REAL,
            icms REAL DEFAULT 0,
            ipi REAL DEFAULT 0,
            pis_cofins REAL DEFAULT 0,
            custo_final REAL,
            margem_lucro REAL DEFAULT 30,
            preco_venda REAL,
            data_entrada TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS orcamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente TEXT,
            data TEXT,
            total REAL,
            itens_json TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Funções Auxiliares de Cálculo
def calcular_custo_e_preco(custo_unit, icms=0, ipi=0, pis_cofins=0, margem=30):
    custo_final = custo_unit * (1 + (icms + ipi + pis_cofins) / 100)
    preco_venda = custo_final * (1 + margem / 100)
    return round(custo_final, 2), round(preco_venda, 2)

# Sessão para Orçamento Atual
if 'orcamento_itens' not in st.session_state:
    st.session_state.orcamento_itens = []

st.title("💊 Sistema de Gestão de Custos e Orçamentos")

# ----------------- SIDEBAR: IMPORTAÇÃO E CADASTRO -----------------
with st.sidebar:
    st.header("📥 Importação de Notas (XML)")
    uploaded_files = st.file_uploader("Suba os arquivos XML da NF-e", type=["xml"], accept_multiple_files=True)
    
    if st.button("Processar Arquivos", use_container_width=True) and uploaded_files:
        conn = get_db_connection()
        c = conn.cursor()
        total_importados = 0
        
        for file in uploaded_files:
            try:
                doc = xmltodict.parse(file.read())
                nfe_data = doc['nfeProc']['NFe']['infNFe'] if 'nfeProc' in doc else doc['NFe']['infNFe']
                fornecedor = nfe_data['emit']['xNome']
                data_emissao = nfe_data['ide']['dhEmi'][:10] if 'dhEmi' in nfe_data['ide'] else str(datetime.now().date())
                
                det = nfe_data['det']
                itens = det if isinstance(det, list) else [det]
                
                for item in itens:
                    prod = item['prod']
                    codigo = prod.get('cProd', '')
                    nome = prod.get('xProd', '').upper()
                    ncm = prod.get('NCM', '')
                    v_un = float(prod.get('vUnCom', 0))
                    
                    custo_final, preco_venda = calcular_custo_e_preco(v_un, margem=30)
                    
                    c.execute('''
                        INSERT INTO produtos (codigo, nome, fornecedor, ncm, custo_unitario, custo_final, margem_lucro, preco_venda, data_entrada)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (codigo, nome, fornecedor, ncm, v_un, custo_final, 30.0, preco_venda, data_emissao))
                    total_importados += 1
            except Exception as e:
                st.error(f"Erro ao processar {file.name}: {e}")
                
        conn.commit()
        conn.close()
        st.success(f"{total_importados} produtos importados com sucesso!")
        st.rerun()

    st.markdown("---")
    with st.expander("✍️ Cadastrar Preço Manual no Banco"):
        with st.form("form_manual"):
            m_cod = st.text_input("Código")
            m_nome = st.text_input("Nome do Produto").upper()
            m_forn = st.text_input("Fornecedor")
            m_custo = st.number_input("Custo Unitário (R$)", min_value=0.0, step=0.1)
            m_margem = st.number_input("Margem de Lucro (%)", value=30.0, step=1.0)
            
            if st.form_submit_button("Salvar no Banco", use_container_width=True):
                if m_nome and m_custo > 0:
                    c_fin, p_vend = calcular_custo_e_preco(m_custo, margem=m_margem)
                    conn = get_db_connection()
                    conn.execute('''
                        INSERT INTO produtos (codigo, nome, fornecedor, custo_unitario, custo_final, margem_lucro, preco_venda, data_entrada)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (m_cod, m_nome, m_forn, m_custo, c_fin, m_margem, p_vend, str(datetime.now().date())))
                    conn.commit()
                    conn.close()
                    st.success("Item cadastrado com sucesso!")
                    st.rerun()
                else:
                    st.warning("Preencha o nome e o custo.")

# ----------------- ABAS PRINCIPAIS -----------------
tab1, tab2, tab3, tab4 = st.tabs([
    "🔍 Inserir no Orçamento", 
    "📋 Orçamento Atual", 
    "📊 Histórico & Tabela",
    "⚙️ Ajuste de Preço em Massa"
])

# ABA 1: Inserir no Orçamento
with tab1:
    st.subheader("1. Inserir Produto no Orçamento")
    origem = st.radio("Origem do Produto:", ["📦 Buscar nas Notas Fiscais (XML)", "✍️ Digitar Item Avulso / Manual"], horizontal=True)
    
    conn = get_db_connection()
    df_prods = pd.read_sql_query("SELECT * FROM produtos ORDER BY id DESC", conn)
    conn.close()
    
    if origem == "📦 Buscar nas Notas Fiscais (XML)":
        if df_prods.empty:
            st.info("Nenhum produto cadastrado ainda. Suba XMLs na barra lateral.")
        else:
            df_prods['display'] = df_prods['nome'] + " | Fornec: " + df_prods['fornecedor'].fillna('') + " | Custo: R$ " + df_prods['custo_unitario'].astype(str)
            escolha = st.selectbox("Selecione o medicamento:", options=df_prods['display'].tolist())
            
            if escolha:
                item_sel = df_prods[df_prods['display'] == escolha].iloc[0]
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Custo Base", f"R$ {item_sel['custo_unitario']:.2f}")
                with col2:
                    qtd = st.number_input("Quantidade", min_value=1, value=1, step=1)
                with col3:
                    margem_orc = st.number_input("Margem (%)", value=float(item_sel['margem_lucro']), step=1.0)
                with col4:
                    _, preco_sugerido = calcular_custo_e_preco(item_sel['custo_unitario'], margem=margem_orc)
                    preco_venda_orc = st.number_input("Preço Unit. Venda (R$)", value=preco_sugerido, step=0.1)
                
                subtotal = round(preco_venda_orc * qtd, 2)
                st.write(f"**Subtotal do Item:** R$ {subtotal:.2f}")
                
                if st.button("➕ Adicionar ao Orçamento", use_container_width=True):
                    st.session_state.orcamento_itens.append({
                        "codigo": item_sel['codigo'],
                        "nome": item_sel['nome'],
                        "fornecedor": item_sel['fornecedor'],
                        "custo_unit": item_sel['custo_unitario'],
                        "margem": margem_orc,
                        "preco_venda": preco_venda_orc,
                        "qtd": qtd,
                        "subtotal": subtotal
                    })
                    st.success(f"{item_sel['nome']} adicionado ao orçamento!")
                    st.rerun()

    else:
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            nome_avulso = st.text_input("Nome do Produto / Descrição").upper()
            qtd_avulso = st.number_input("Quantidade", min_value=1, value=1, step=1, key="qtd_av")
        with col_m2:
            custo_avulso = st.number_input("Custo Unitário (R$)", min_value=0.0, step=0.1, key="custo_av")
            margem_avulso = st.number_input("Margem (%)", value=30.0, step=1.0, key="marg_av")
            
        _, preco_sug_avulso = calcular_custo_e_preco(custo_avulso, margem=margem_avulso)
        preco_venda_av = st.number_input("Preço Unit. Venda (R$)", value=preco_sug_avulso, step=0.1, key="pv_av")
        subtotal_av = round(preco_venda_av * qtd_avulso, 2)
        
        if st.button("➕ Adicionar Item Avulso", use_container_width=True):
            if nome_avulso:
                st.session_state.orcamento_itens.append({
                    "codigo": "AVULSO",
                    "nome": nome_avulso,
                    "fornecedor": "MANUAL",
                    "custo_unit": custo_avulso,
                    "margem": margem_avulso,
                    "preco_venda": preco_venda_av,
                    "qtd": qtd_avulso,
                    "subtotal": subtotal_av
                })
                st.success(f"{nome_avulso} adicionado ao orçamento!")
                st.rerun()
            else:
                st.warning("Preencha o nome do produto.")

# ABA 2: Orçamento Atual & Geração de PDF
with tab2:
    st.subheader("2. Itens no Orçamento Atual")
    if not st.session_state.orcamento_itens:
        st.info("Nenhum item adicionado ao orçamento até o momento.")
    else:
        df_atual = pd.DataFrame(st.session_state.orcamento_itens)
        st.dataframe(df_atual[['nome', 'fornecedor', 'qtd', 'custo_unit', 'margem', 'preco_venda', 'subtotal']], use_container_width=True)
        
        total_orcamento = df_atual['subtotal'].sum()
        total_custo = (df_atual['custo_unit'] * df_atual['qtd']).sum()
        lucro_estimado = total_orcamento - total_custo
        
        c_tot1, c_tot2, c_tot3 = st.columns(3)
        c_tot1.metric("Valor Total do Orçamento", f"R$ {total_orcamento:.2f}")
        c_tot2.metric("Custo Total Estimado", f"R$ {total_custo:.2f}")
        c_tot3.metric("Lucro Estimado", f"R$ {lucro_estimado:.2f}")
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            nome_cliente = st.text_input("Nome do Cliente / Paciente", value="Cliente")
        
        with col_btn2:
            st.write("")
            st.write("")
            if st.button("🗑️ Limpar Todo o Orçamento", use_container_width=True):
                st.session_state.orcamento_itens = []
                st.rerun()
                
        # Gerador de PDF
        def gerar_pdf(itens, cliente, total):
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", 'B', 16)
            pdf.cell(0, 10, "ORÇAMENTO DE MEDICAMENTOS", ln=True, align="C")
            pdf.ln(5)
            
            pdf.set_font("Arial", '', 11)
            pdf.cell(0, 7, f"Cliente: {cliente}", ln=True)
            pdf.cell(0, 7, f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True)
            pdf.ln(5)
            
            pdf.set_font("Arial", 'B', 10)
            pdf.cell(100, 8, "Descrição", border=1)
            pdf.cell(25, 8, "Qtd", border=1, align="C")
            pdf.cell(30, 8, "Unitário (R$)", border=1, align="R")
            pdf.cell(35, 8, "Total (R$)", border=1, align="R")
            pdf.ln()
            
            pdf.set_font("Arial", '', 10)
            for item in itens:
                pdf.cell(100, 8, item['nome'][:40], border=1)
                pdf.cell(25, 8, str(item['qtd']), border=1, align="C")
                pdf.cell(30, 8, f"{item['preco_venda']:.2f}", border=1, align="R")
                pdf.cell(35, 8, f"{item['subtotal']:.2f}", border=1, align="R")
                pdf.ln()
                
            pdf.set_font("Arial", 'B', 11)
            pdf.cell(155, 10, "TOTAL DO ORÇAMENTO:", border=1, align="R")
            pdf.cell(35, 10, f"R$ {total:.2f}", border=1, align="R")
            return bytes(pdf.output())

        pdf_bytes = gerar_pdf(st.session_state.orcamento_itens, nome_cliente, total_orcamento)
        st.download_button(
            label="📄 Baixar Orçamento em PDF",
            data=pdf_bytes,
            file_name=f"Orcamento_{nome_cliente}_{datetime.now().strftime('%d%m%Y')}.pdf",
            mime="application/pdf",
            use_container_width=True
        )

# ABA 3: Histórico e Visualização Geral
with tab3:
    st.subheader("3. Histórico e Produtos Cadastrados")
    conn = get_db_connection()
    df_view = pd.read_sql_query("SELECT id, codigo, nome, fornecedor, custo_unitario, margem_lucro, preco_venda, data_entrada FROM produtos ORDER BY id DESC", conn)
    conn.close()
    
    if not df_view.empty:
        st.dataframe(df_view, use_container_width=True)
    else:
        st.info("Nenhum dado cadastrado.")

# ABA 4: ⚙️ AJUSTE DE PREÇOS EM MASSA
with tab4:
    st.subheader("⚙️ Reajuste de Margem e Preços em Massa")
    
    conn = get_db_connection()
    df_all = pd.read_sql_query("SELECT * FROM produtos", conn)
    conn.close()
    
    if df_all.empty:
        st.info("Cadastre ou importe produtos via XML para poder utilizar o reajuste em massa.")
    else:
        st.markdown("##### 1. Filtrar Itens para Reajuste")
        
        fornecedores_lista = ["TODOS"] + sorted([f for f in df_all['fornecedor'].dropna().unique() if f])
        
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            sel_fornec = st.selectbox("Filtrar por Fornecedor / Distribuidora:", fornecedores_lista)
        with col_f2:
            busca_nome = st.text_input("Filtrar por Palavra-chave no Nome (opcional):").strip().upper()
            
        # Aplicação dos Filtros
        df_filtrado = df_all.copy()
        if sel_fornec != "TODOS":
            df_filtrado = df_filtrado[df_filtrado['fornecedor'] == sel_fornec]
        if busca_nome:
            df_filtrado = df_filtrado[df_filtrado['nome'].str.contains(busca_nome, na=False)]
            
        st.write(f"🔎 **{len(df_filtrado)}** produto(s) selecionado(s) para alteração.")
        
        if len(df_filtrado) > 0:
            st.markdown("---")
            st.markdown("##### 2. Definir a Regra de Reajuste")
            
            tipo_ajuste = st.radio(
                "Tipo de Alteração:",
                [
                    "Definir Nova Margem Fixa (%) para todos", 
                    "Acréscimo / Redução na Margem Atual (+/- %)",
                    "Acréscimo Percentual direto no Preço de Venda (+/- %)"
                ],
                horizontal=True
            )
            
            col_v1, _ = st.columns([2, 2])
            with col_v1:
                if tipo_ajuste == "Definir Nova Margem Fixa (%) para todos":
                    novo_valor = st.number_input("Nova Margem de Lucro (%):", min_value=0.0, value=35.0, step=1.0)
                    df_filtrado['nova_margem'] = novo_valor
                    df_filtrado['novo_preco_venda'] = df_filtrado.apply(
                        lambda row: round(row['custo_final'] * (1 + novo_valor / 100), 2), axis=1
                    )
                elif tipo_ajuste == "Acréscimo / Redução na Margem Atual (+/- %)":
                    variacao_margem = st.number_input("Variação na Margem (% ex: +5 ou -3):", value=5.0, step=0.5)
                    df_filtrado['nova_margem'] = df_filtrado['margem_lucro'] + variacao_margem
                    df_filtrado['novo_preco_venda'] = df_filtrado.apply(
                        lambda row: round(row['custo_final'] * (1 + row['nova_margem'] / 100), 2), axis=1
                    )
                else:
                    perc_preco = st.number_input("Porcentagem sobre o Preço Atual (% ex: +5 ou -5):", value=5.0, step=0.5)
                    df_filtrado['novo_preco_venda'] = df_filtrado.apply(
                        lambda row: round(row['preco_venda'] * (1 + perc_preco / 100), 2), axis=1
                    )
                    df_filtrado['nova_margem'] = df_filtrado.apply(
                        lambda row: round(((row['novo_preco_venda'] - row['custo_final']) / row['custo_final']) * 100, 2) if row['custo_final'] > 0 else row['margem_lucro'], axis=1
                    )

            st.markdown("##### 3. Pré-visualização das Alterações")
            colunas_preview = ['nome', 'fornecedor', 'custo_unitario', 'margem_lucro', 'nova_margem', 'preco_venda', 'novo_preco_venda']
            df_preview = df_filtrado[colunas_preview].rename(columns={
                'nome': 'Medicamento',
                'fornecedor': 'Fornecedor',
                'custo_unitario': 'Custo Base',
                'margem_lucro': 'Margem Atual (%)',
                'nova_margem': 'Nova Margem (%)',
                'preco_venda': 'Preço Venda Atual (R$)',
                'novo_preco_venda': 'Novo Preço Venda (R$)'
            })
            st.dataframe(df_preview, use_container_width=True)
            
            st.markdown("---")
            if st.button("🚀 Confirmar e Aplicar Reajuste em Massa no Banco", type="primary", use_container_width=True):
                conn = get_db_connection()
                c = conn.cursor()
                for _, row in df_filtrado.iterrows():
                    c.execute('''
                        UPDATE produtos 
                        SET margem_lucro = ?, preco_venda = ?
                        WHERE id = ?
                    ''', (float(row['nova_margem']), float(row['novo_preco_venda']), int(row['id'])))
                conn.commit()
                conn.close()
                st.success(f"🎉 Reajuste aplicado com sucesso em {len(df_filtrado)} produto(s)!")
                st.rerun()
