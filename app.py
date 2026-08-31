import streamlit as st
import sqlite3
import pandas as pd
import xmltodict
from fpdf import FPDF
from datetime import datetime
import urllib.parse
import requests

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
    custo_final = round(custo_unit * (1 + (icms + ipi + pis_cofins) / 100), 2)
    preco_venda = round(custo_final * (1 + margem / 100), 2)
    return custo_final, preco_venda

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
                    v_un = round(float(prod.get('vUnCom', 0)), 2)
                    
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
        st.toast(f"✅ {total_importados} produtos importados com sucesso!")
        st.rerun()

    st.markdown("---")
    with st.expander("✍️ Cadastrar Preço Manual no Banco"):
        with st.form("form_manual"):
            m_cod = st.text_input("Código")
            m_nome = st.text_input("Nome do Produto").upper()
            m_forn = st.text_input("Fornecedor")
            m_custo = st.number_input("Custo Unitário (R$)", min_value=0.0, step=0.1, format="%.2f")
            m_margem = st.number_input("Margem de Lucro (%)", value=30.0, step=1.0)
            
            if st.form_submit_button("Salvar no Banco", use_container_width=True):
                if m_nome and m_custo > 0:
                    c_fin, p_vend = calcular_custo_e_preco(m_custo, margem=m_margem)
                    conn = get_db_connection()
                    conn.execute('''
                        INSERT INTO produtos (codigo, nome, fornecedor, custo_unitario, custo_final, margem_lucro, preco_venda, data_entrada)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (m_cod, m_nome, m_forn, round(m_custo, 2), c_fin, m_margem, p_vend, str(datetime.now().date())))
                    conn.commit()
                    conn.close()
                    st.toast("✅ Item cadastrado com sucesso!")
                    st.rerun()
                else:
                    st.warning("Preencha o nome e o custo.")

# ----------------- ABAS PRINCIPAIS -----------------
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🔍 Inserir no Orçamento", 
    "📋 Orçamento Atual & Negociação", 
    "🌐 Pesquisa na Internet",
    "⚙️ Reajuste em Massa no Banco",
    "📊 Histórico Geral"
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
            df_prods['display'] = df_prods['nome'] + " | Fornec: " + df_prods['fornecedor'].fillna('') + " | Custo: R$ " + df_prods['custo_unitario'].apply(lambda x: f"{float(x):.2f}")
            escolha = st.selectbox("Selecione o medicamento:", options=df_prods['display'].tolist())
            
            if escolha:
                item_sel = df_prods[df_prods['display'] == escolha].iloc[0]
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Custo Base", f"R$ {float(item_sel['custo_unitario']):.2f}")
                with col2:
                    qtd = st.number_input("Quantidade", min_value=1, value=1, step=1)
                with col3:
                    margem_orc = st.number_input("Margem (%)", value=float(item_sel['margem_lucro']), step=1.0)
                with col4:
                    _, preco_sugerido = calcular_custo_e_preco(float(item_sel['custo_unitario']), margem=margem_orc)
                    preco_venda_orc = st.number_input("Preço Unit. Venda (R$)", value=preco_sugerido, step=0.1, format="%.2f")
                
                subtotal = round(preco_venda_orc * qtd, 2)
                st.write(f"**Subtotal do Item:** R$ {subtotal:.2f}")
                
                if st.button("➕ Adicionar ao Orçamento", use_container_width=True):
                    st.session_state.orcamento_itens.append({
                        "codigo": item_sel['codigo'],
                        "nome": item_sel['nome'],
                        "fornecedor": item_sel['fornecedor'],
                        "custo_unit": float(item_sel['custo_unitario']),
                        "margem": margem_orc,
                        "preco_venda": preco_venda_orc,
                        "qtd": qtd,
                        "subtotal": subtotal
                    })
                    st.toast(f"✅ {item_sel['nome']} adicionado ao orçamento!")
                    st.rerun()

    else:
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            nome_avulso = st.text_input("Nome do Produto / Descrição").upper()
            qtd_avulso = st.number_input("Quantidade", min_value=1, value=1, step=1, key="qtd_av")
        with col_m2:
            custo_avulso = st.number_input("Custo Unitário (R$)", min_value=0.0, step=0.1, format="%.2f", key="custo_av")
            margem_avulso = st.number_input("Margem (%)", value=30.0, step=1.0, key="marg_av")
            
        _, preco_sug_avulso = calcular_custo_e_preco(custo_avulso, margem=margem_avulso)
        preco_venda_av = st.number_input("Preço Unit. Venda (R$)", value=preco_sug_avulso, step=0.1, format="%.2f", key="pv_av")
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
                st.toast(f"✅ {nome_avulso} adicionado ao orçamento!")
                st.rerun()
            else:
                st.warning("Preencha o nome do produto.")

# ABA 2: Orçamento Atual & Negociação em Lote
with tab2:
    st.subheader("2. Itens no Orçamento Atual")
    if not st.session_state.orcamento_itens:
        st.info("Nenhum item adicionado ao orçamento até o momento.")
    else:
        # Painel de Ajuste em Massa no Orçamento Aberto
        with st.expander("⚡ Aplicar Desconto ou Reajuste em Massa neste Orçamento", expanded=False):
            col_aj1, col_aj2, col_aj3 = st.columns([2, 1, 1])
            with col_aj1:
                tipo_aj_orc = st.selectbox(
                    "Ação:",
                    ["Aplicar Desconto Geral (%) no Preço", "Aplicar Acréscimo Geral (%) no Preço", "Definir Nova Margem Fixa (%) para todos os itens"]
                )
            with col_aj2:
                valor_aj_orc = st.number_input("Percentual (%):", min_value=0.0, value=5.0, step=0.5)
            with col_aj3:
                st.write("")
                st.write("")
                if st.button("Aplicar a Todos os Itens", use_container_width=True):
                    for item in st.session_state.orcamento_itens:
                        if tipo_aj_orc == "Aplicar Desconto Geral (%) no Preço":
                            item['preco_venda'] = round(item['preco_venda'] * (1 - valor_aj_orc / 100), 2)
                            if item['custo_unit'] > 0:
                                item['margem'] = round(((item['preco_venda'] - item['custo_unit']) / item['custo_unit']) * 100, 1)
                        elif tipo_aj_orc == "Aplicar Acréscimo Geral (%) no Preço":
                            item['preco_venda'] = round(item['preco_venda'] * (1 + valor_aj_orc / 100), 2)
                            if item['custo_unit'] > 0:
                                item['margem'] = round(((item['preco_venda'] - item['custo_unit']) / item['custo_unit']) * 100, 1)
                        else:
                            item['margem'] = valor_aj_orc
                            item['preco_venda'] = round(item['custo_unit'] * (1 + valor_aj_orc / 100), 2)
                        
                        item['subtotal'] = round(item['preco_venda'] * item['qtd'], 2)
                    st.toast("✅ Valores recalculados com sucesso!")
                    st.rerun()

        st.markdown("##### Lista de Itens Adicionados:")
        
        # Cabeçalho da Lista com Botão de Excluir Individual
        c_h1, c_h2, c_h3, c_h4, c_h5, c_h6 = st.columns([4, 1, 2, 2, 2, 1])
        c_h1.write("**Descrição**")
        c_h2.write("**Qtd**")
        c_h3.write("**Custo Unit.**")
        c_h4.write("**Preço Venda**")
        c_h5.write("**Subtotal**")
        c_h6.write("**Remover**")

        idx_remover = None
        for i, item in enumerate(st.session_state.orcamento_itens):
            col_l1, col_l2, col_l3, col_l4, col_l5, col_l6 = st.columns([4, 1, 2, 2, 2, 1])
            col_l1.write(f"**{item['nome']}**")
            col_l2.write(str(item['qtd']))
            col_l3.write(f"R$ {item['custo_unit']:.2f}")
            col_l4.write(f"R$ {item['preco_venda']:.2f} ({item['margem']:.0f}%)")
            col_l5.write(f"**R$ {item['subtotal']:.2f}**")
            if col_l6.button("🗑️", key=f"del_{i}", help="Remover apenas este item"):
                idx_remover = i

        if idx_remover is not None:
            removido = st.session_state.orcamento_itens.pop(idx_remover)
            st.toast(f"🗑️ {removido['nome']} removido!")
            st.rerun()

        st.markdown("---")

        # Métricas de Resumo
        total_orcamento = sum(item['subtotal'] for item in st.session_state.orcamento_itens)
        total_custo = sum(item['custo_unit'] * item['qtd'] for item in st.session_state.orcamento_itens)
        lucro_estimado = total_orcamento - total_custo
        margem_geral = ((lucro_estimado / total_custo) * 100) if total_custo > 0 else 0
        
        c_tot1, c_tot2, c_tot3, c_tot4 = st.columns(4)
        c_tot1.metric("Valor Total do Orçamento", f"R$ {total_orcamento:.2f}")
        c_tot2.metric("Custo Total Estimado", f"R$ {total_custo:.2f}")
        c_tot3.metric("Lucro Estimado", f"R$ {lucro_estimado:.2f}")
        c_tot4.metric("Margem Média da Venda", f"{margem_geral:.1f}%")
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            nome_cliente = st.text_input("Nome do Cliente / Paciente", value="Cliente")
        
        with col_btn2:
            st.write("")
            st.write("")
            if st.button("🗑️ Limpar Todo o Orçamento", use_container_width=True):
                st.session_state.orcamento_itens = []
                st.toast("Orçamento esvaziado!")
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
                pdf.cell(100, 8, str(item['nome'])[:40], border=1)
                pdf.cell(25, 8, str(item['qtd']), border=1, align="C")
                pdf.cell(30, 8, f"{float(item['preco_venda']):.2f}", border=1, align="R")
                pdf.cell(35, 8, f"{float(item['subtotal']):.2f}", border=1, align="R")
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

# ABA 3: 🌐 Pesquisa na Internet & Tabela CMED
with tab3:
    st.subheader("🌐 Pesquisa de Medicamentos na Web & Preço de Mercado")
    
    termo_busca = st.text_input("Digite o nome do remédio ou princípio ativo:").strip()
    
    if termo_busca:
        termo_encoded = urllib.parse.quote(termo_busca)
        
        st.markdown("##### 🔗 Atalhos de Consulta Rápida:")
        col_link1, col_link2, col_link3 = st.columns(3)
        with col_link1:
            st.link_button("🔎 Consulta Remédios", f"https://consultaremedios.com.br/busca?termo={termo_encoded}", use_container_width=True)
        with col_link2:
            st.link_button("🏛️ Tabela CMED / Anvisa", f"https://www.gov.br/anvisa/pt-br/assuntos/medicamentos/cmed/precos", use_container_width=True)
        with col_link3:
            st.link_button("🌐 Buscar no Google Shopping", f"https://www.google.com/search?tbm=shop&q={termo_encoded}", use_container_width=True)
            
        st.markdown("---")
        st.markdown("##### ⚡ Adicionar ao Orçamento a partir da Pesquisa Web:")
        with st.form("form_web_orc"):
            col_w1, col_w2 = st.columns(2)
            with col_w1:
                w_nome = st.text_input("Nome do Produto Encontrado", value=termo_busca.upper())
                w_qtd = st.number_input("Quantidade", min_value=1, value=1, step=1)
            with col_w2:
                w_custo = st.number_input("Custo / PMC Encontrado (R$)", min_value=0.0, step=0.1, format="%.2f")
                w_margem = st.number_input("Margem (%)", value=30.0, step=1.0)
                
            _, w_preco_venda = calcular_custo_e_preco(w_custo, margem=w_margem)
            w_subtotal = round(w_preco_venda * w_qtd, 2)
            st.write(f"Preço Unitário Calculado: **R$ {w_preco_venda:.2f}** | Subtotal: **R$ {w_subtotal:.2f}**")
            
            if st.form_submit_button("➕ Adicionar Direto no Orçamento", use_container_width=True):
                if w_nome and w_custo > 0:
                    st.session_state.orcamento_itens.append({
                        "codigo": "WEB",
                        "nome": w_nome,
                        "fornecedor": "PESQUISA WEB",
                        "custo_unit": w_custo,
                        "margem": w_margem,
                        "preco_venda": w_preco_venda,
                        "qtd": w_qtd,
                        "subtotal": w_subtotal
                    })
                    st.toast(f"✅ {w_nome} adicionado ao orçamento!")
                    st.rerun()
                else:
                    st.warning("Preencha o nome e o custo.")

# ABA 4: ⚙️ Reajuste em Massa no Banco de Dados
with tab4:
    st.subheader("⚙️ Reajuste de Margem e Preços em Massa (Banco Geral)")
    
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
                st.toast(f"🎉 Reajuste aplicado em {len(df_filtrado)} produto(s)!")
                st.rerun()

# ABA 5: Histórico Geral
with tab5:
    st.subheader("5. Histórico e Produtos Cadastrados")
    conn = get_db_connection()
    df_view = pd.read_sql_query("SELECT id, codigo, nome, fornecedor, custo_unitario, margem_lucro, preco_venda, data_entrada FROM produtos ORDER BY id DESC", conn)
    conn.close()
    
    if not df_view.empty:
        st.dataframe(df_view, use_container_width=True)
    else:
        st.info("Nenhum dado cadastrado.")
