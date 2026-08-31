import streamlit as st
import sqlite3
import pandas as pd
import xmltodict
from fpdf import FPDF
from datetime import datetime
import urllib.parse
import json
import os

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

# Sessão para Orçamento Atual e Nome do Cliente
if 'orcamento_itens' not in st.session_state:
    st.session_state.orcamento_itens = []

if 'nome_cliente' not in st.session_state:
    st.session_state.nome_cliente = ""

st.title("💊 Sistema de Gestão de Custos e Orçamentos")

# ----------------- SIDEBAR: IMPORTAÇÃO, CADASTRO E MANUTENÇÃO -----------------
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
            m_custo = st.number_input("Custo da Caixa/Item (R$)", min_value=0.0, step=0.1, format="%.2f")
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

    st.markdown("---")
    with st.expander("🛠️ Manutenção & Backup"):
        if os.path.exists('farmacia.db'):
            with open('farmacia.db', 'rb') as f:
                db_bytes = f.read()
            st.download_button(
                label="💾 Fazer Backup do Banco (Download)",
                data=db_bytes,
                file_name=f"backup_farmacia_{datetime.now().strftime('%d%m%Y_%H%M')}.db",
                mime="application/x-sqlite3",
                use_container_width=True
            )
        
        if st.button("🧹 Limpar Produtos Duplicados", use_container_width=True):
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('''
                DELETE FROM produtos
                WHERE id NOT IN (
                    SELECT MAX(id)
                    FROM produtos
                    GROUP BY nome
                )
            ''')
            removidos = c.rowcount
            conn.commit()
            conn.close()
            st.toast(f"✅ {removidos} registros duplicados removidos!")
            st.rerun()
            
        if st.button("⚡ Otimizar Espaço (Compactar)", use_container_width=True):
            conn = sqlite3.connect('farmacia.db')
            conn.execute("VACUUM")
            conn.close()
            st.toast("✅ Banco de dados compactado com sucesso!")

# ----------------- CLASSE PERSONALIZADA DE PDF -----------------
class PDFOrcamento(FPDF):
    def header(self):
        self.set_fill_color(30, 58, 138)
        self.rect(0, 0, 210, 24, 'F')
        
        self.set_xy(10, 5)
        self.set_font('Arial', 'B', 14)
        self.set_text_color(255, 255, 255)
        self.cell(0, 7, 'GESTAO FARMACEUTICA & PROPOSTA COMERCIAL', 0, 1, 'L')
        
        self.set_font('Arial', '', 9)
        self.set_text_color(200, 220, 255)
        self.cell(0, 5, 'Sistema de Gestao de Custos e Orcamentos de Medicamentos', 0, 1, 'L')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Pagina {self.page_no()} | Documento gerado em {datetime.now().strftime("%d/%m/%Y %H:%M")}', 0, 0, 'C')

# ----------------- ABAS PRINCIPAIS -----------------
tab1, tab2, tab3, tab4 = st.tabs([
    "🔍 Inserir no Orçamento", 
    "📋 Orçamento Atual & Negociação", 
    "📂 Orçamentos Salvos",
    "📊 Histórico de Produtos"
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
                
                # Atalhos de Pesquisa na Web para o item selecionado
                termo_encoded = urllib.parse.quote(str(item_sel['nome']))
                st.markdown(f"**🌐 Consultar Preço de Mercado na Web para:** `{item_sel['nome']}`")
                c_web1, c_web2, c_web3 = st.columns(3)
                with c_web1:
                    st.link_button("🔎 Consulta Remédios", f"https://consultaremedios.com.br/busca?termo={termo_encoded}", use_container_width=True)
                with c_web2:
                    st.link_button("🏛️ Tabela CMED / Anvisa", "https://www.gov.br/anvisa/pt-br/assuntos/medicamentos/cmed/precos", use_container_width=True)
                with c_web3:
                    st.link_button("🌐 Google Shopping", f"https://www.google.com/search?tbm=shop&q={termo_encoded}", use_container_width=True)
                
                st.markdown("---")
                
                # Comparativo Histórico de Fornecedores do mesmo medicamento
                df_mesmo_item = df_prods[df_prods['nome'] == item_sel['nome']]
                if len(df_mesmo_item) > 1:
                    with st.expander("📦 Ver histórico de preços deste produto em outros fornecedores"):
                        st.dataframe(df_mesmo_item[['data_entrada', 'fornecedor', 'custo_unitario', 'margem_lucro', 'preco_venda']].rename(columns={
                            'data_entrada': 'Data NF',
                            'fornecedor': 'Fornecedor',
                            'custo_unitario': 'Custo Base (R$)',
                            'margem_lucro': 'Margem (%)',
                            'preco_venda': 'Preço Venda (R$)'
                        }), use_container_width=True)

                # Opção de Venda: Caixa Fechada ou Fracionado por Unidade
                tipo_venda = st.radio("Forma de Venda:", ["📦 Caixa Fechada", "💊 Fracionado / Por Unidade (Comprimido/Ampola)"], horizontal=True)
                
                custo_base_calc = float(item_sel['custo_unitario'])
                rotulo_desc = item_sel['nome']
                
                if tipo_venda == "💊 Fracionado / Por Unidade (Comprimido/Ampola)":
                    col_u1, _ = st.columns([1, 3])
                    with col_u1:
                        qtd_por_caixa = st.number_input("Quantas unidades vêm na caixa?", min_value=1, value=30, step=1)
                    if qtd_por_caixa > 0:
                        custo_base_calc = custo_base_calc / qtd_por_caixa
                        rotulo_desc = f"{item_sel['nome']} (UNIDADE)"
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Custo Base Considerado", f"R$ {custo_base_calc:.2f}")
                with col2:
                    qtd = st.number_input("Quantidade a Vender", min_value=1, value=1, step=1)
                with col3:
                    margem_orc = st.number_input("Margem (%)", value=float(item_sel['margem_lucro']), step=1.0)
                with col4:
                    _, preco_sugerido = calcular_custo_e_preco(custo_base_calc, margem=margem_orc)
                    preco_venda_orc = st.number_input("Preço Unit. Venda (R$)", value=preco_sugerido, step=0.01, format="%.2f")
                
                subtotal = round(preco_venda_orc * qtd, 2)
                st.write(f"**Subtotal do Item:** R$ {subtotal:.2f}")
                
                if st.button("➕ Adicionar ao Orçamento", use_container_width=True):
                    st.session_state.orcamento_itens.append({
                        "codigo": item_sel['codigo'],
                        "nome": rotulo_desc,
                        "fornecedor": item_sel['fornecedor'],
                        "custo_unit": round(custo_base_calc, 2),
                        "margem": margem_orc,
                        "preco_venda": preco_venda_orc,
                        "qtd": qtd,
                        "subtotal": subtotal
                    })
                    st.toast(f"✅ {rotulo_desc} adicionado ao orçamento!")
                    st.rerun()

    else:
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            nome_avulso = st.text_input("Nome do Produto / Descrição").upper()
            tipo_venda_av = st.radio("Forma de Venda (Manual):", ["📦 Caixa Fechada", "💊 Fracionado / Por Unidade"], horizontal=True, key="tp_av")
            qtd_avulso = st.number_input("Quantidade a Vender", min_value=1, value=1, step=1, key="qtd_av")
        with col_m2:
            custo_avulso_raw = st.number_input("Custo Base (R$)", min_value=0.0, step=0.1, format="%.2f", key="custo_av")
            if tipo_venda_av == "💊 Fracionado / Por Unidade":
                qtd_cx_av = st.number_input("Unidades por Caixa:", min_value=1, value=30, step=1, key="qcx_av")
                custo_avulso = custo_avulso_raw / qtd_cx_av if qtd_cx_av > 0 else custo_avulso_raw
                nome_avulso_final = f"{nome_avulso} (UNIDADE)" if nome_avulso else ""
            else:
                custo_avulso = custo_avulso_raw
                nome_avulso_final = nome_avulso
                
            margem_avulso = st.number_input("Margem (%)", value=30.0, step=1.0, key="marg_av")
            
        _, preco_sug_avulso = calcular_custo_e_preco(custo_avulso, margem=margem_avulso)
        preco_venda_av = st.number_input("Preço Unit. Venda (R$)", value=preco_sug_avulso, step=0.01, format="%.2f", key="pv_av")
        subtotal_av = round(preco_venda_av * qtd_avulso, 2)
        
        if st.button("➕ Adicionar Item Avulso", use_container_width=True):
            if nome_avulso_final:
                st.session_state.orcamento_itens.append({
                    "codigo": "AVULSO",
                    "nome": nome_avulso_final,
                    "fornecedor": "MANUAL",
                    "custo_unit": round(custo_avulso, 2),
                    "margem": margem_avulso,
                    "preco_venda": preco_venda_av,
                    "qtd": qtd_avulso,
                    "subtotal": subtotal_av
                })
                st.toast(f"✅ {nome_avulso_final} adicionado ao orçamento!")
                st.rerun()
            else:
                st.warning("Preencha o nome do produto.")

# ABA 2: Orçamento Atual, Negociação em Lote e WhatsApp
with tab2:
    st.subheader("2. Itens no Orçamento Atual")
    if not st.session_state.orcamento_itens:
        st.info("Nenhum item adicionado ao orçamento até o momento.")
    else:
        # Campo do Nome do Cliente integrado ao estado
        st.session_state.nome_cliente = st.text_input(
            "👤 Nome do Cliente / Paciente:", 
            value=st.session_state.nome_cliente, 
            placeholder="Digite o nome completo do cliente..."
        )
        nome_cliente_final = st.session_state.nome_cliente.strip() if st.session_state.nome_cliente.strip() else "CLIENTE"

        # Ferramenta de Desconto / Reajuste Geral no Orçamento do Cliente
        with st.expander("⚡ Aplicar Desconto ou Reajuste em Massa no Orçamento", expanded=False):
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

        st.markdown("##### Lista de Itens do Orçamento:")
        
        # Tabela com botão de exclusão individual (🗑️)
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

        # Resumo Financeiro
        total_orcamento = sum(item['subtotal'] for item in st.session_state.orcamento_itens)
        total_custo = sum(item['custo_unit'] * item['qtd'] for item in st.session_state.orcamento_itens)
        lucro_estimado = total_orcamento - total_custo
        margem_geral = ((lucro_estimado / total_custo) * 100) if total_custo > 0 else 0
        
        c_tot1, c_tot2, c_tot3, c_tot4 = st.columns(4)
        c_tot1.metric("Valor Total do Orçamento", f"R$ {total_orcamento:.2f}")
        c_tot2.metric("Custo Total Estimado", f"R$ {total_custo:.2f}")
        c_tot3.metric("Lucro Estimado", f"R$ {lucro_estimado:.2f}")
        c_tot4.metric("Margem Média da Venda", f"{margem_geral:.1f}%")
        
        # Trava de Segurança / Alerta de Margem Baixa
        if margem_geral < 15.0:
            st.error(f"⚠️ **Atenção:** A margem de lucro desta venda está em **{margem_geral:.1f}%** (abaixo do piso de segurança recomendado de 15%).")

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("💾 Salvar Orçamento no Histórico do Sistema", use_container_width=True):
                conn = get_db_connection()
                conn.execute('''
                    INSERT INTO orcamentos (cliente, data, total, itens_json)
                    VALUES (?, ?, ?, ?)
                ''', (nome_cliente_final, datetime.now().strftime('%d/%m/%Y %H:%M'), total_orcamento, json.dumps(st.session_state.orcamento_itens)))
                conn.commit()
                conn.close()
                st.toast("✅ Orçamento gravado no histórico!")
        
        with col_btn2:
            if st.button("🗑️ Limpar Todo o Orçamento", use_container_width=True):
                st.session_state.orcamento_itens = []
                st.session_state.nome_cliente = ""
                st.toast("Orçamento esvaziado!")
                st.rerun()

        # Montagem do Link do WhatsApp
        msg_itens = "\n".join([f"- {item['qtd']}x {item['nome']}: R$ {item['subtotal']:.2f}" for item in st.session_state.orcamento_itens])
        texto_whatsapp = f"*ORÇAMENTO DE MEDICAMENTOS*\n\n*Cliente:* {nome_cliente_final}\n*Data:* {datetime.now().strftime('%d/%m/%Y')}\n\n*Itens:*\n{msg_itens}\n\n*VALOR TOTAL:* R$ {total_orcamento:.2f}\n\n_Validade da proposta: 7 dias._"
        whatsapp_url = f"https://api.whatsapp.com/send?text={urllib.parse.quote(texto_whatsapp)}"

        col_act1, col_act2 = st.columns(2)
        with col_act1:
            st.link_button("📲 Enviar Resumo pelo WhatsApp", whatsapp_url, use_container_width=True)

        # Gerador de PDF Profissional
        def gerar_pdf(itens, cliente, total):
            pdf = PDFOrcamento()
            pdf.add_page()
            
            pdf.set_fill_color(245, 247, 250)
            pdf.set_draw_color(210, 215, 225)
            pdf.rect(10, 28, 190, 20, 'FD')
            
            pdf.set_xy(14, 30)
            pdf.set_font("Arial", 'B', 10)
            pdf.set_text_color(50, 50, 50)
            pdf.cell(30, 6, "CLIENTE:", 0, 0)
            pdf.set_font("Arial", '', 10)
            pdf.cell(80, 6, str(cliente).upper(), 0, 0)
            
            pdf.set_font("Arial", 'B', 10)
            pdf.cell(30, 6, "DATA:", 0, 0)
            pdf.set_font("Arial", '', 10)
            pdf.cell(40, 6, datetime.now().strftime('%d/%m/%Y %H:%M'), 0, 1)
            
            pdf.set_xy(14, 38)
            pdf.set_font("Arial", 'B', 10)
            pdf.cell(30, 6, "STATUS:", 0, 0)
            pdf.set_font("Arial", '', 10)
            pdf.cell(80, 6, "Proposta Comercial / Em Aberto", 0, 0)
            
            pdf.set_font("Arial", 'B', 10)
            pdf.cell(30, 6, "VALIDADE:", 0, 0)
            pdf.set_font("Arial", '', 10)
            pdf.cell(40, 6, "7 dias", 0, 1)
            
            pdf.ln(10)
            
            pdf.set_fill_color(30, 58, 138)
            pdf.set_text_color(255, 255, 255)
            pdf.set_draw_color(30, 58, 138)
            pdf.set_font("Arial", 'B', 9)
            
            pdf.cell(105, 9, "  DESCRICAO DO ITEM / MEDICAMENTO", border=1, fill=True)
            pdf.cell(20, 9, "QTD", border=1, align="C", fill=True)
            pdf.cell(30, 9, "UNITARIO (R$)", border=1, align="R", fill=True)
            pdf.cell(35, 9, "SUBTOTAL (R$)", border=1, align="R", fill=True)
            pdf.ln()
            
            pdf.set_font("Arial", '', 9)
            pdf.set_draw_color(230, 230, 230)
            
            fill = False
            for item in itens:
                pdf.set_fill_color(248, 249, 250) if fill else pdf.set_fill_color(255, 255, 255)
                pdf.set_text_color(40, 40, 40)
                
                nome_formatado = "  " + str(item['nome'])[:45]
                pdf.cell(105, 8, nome_formatado, border='LRB', fill=True)
                pdf.cell(20, 8, str(item['qtd']), border='LRB', align="C", fill=True)
                pdf.cell(30, 8, f"{float(item['preco_venda']):.2f}", border='LRB', align="R", fill=True)
                pdf.cell(35, 8, f"{float(item['subtotal']):.2f}", border='LRB', align="R", fill=True)
                pdf.ln()
                fill = not fill
                
            pdf.ln(2)
            pdf.set_fill_color(235, 243, 255)
            pdf.set_draw_color(30, 58, 138)
            pdf.set_text_color(30, 58, 138)
            pdf.set_font("Arial", 'B', 11)
            pdf.cell(155, 11, "TOTAL GERAL DA PROPOSTA:  ", border=1, align="R", fill=True)
            pdf.cell(35, 11, f"R$ {total:.2f}", border=1, align="R", fill=True)
            
            pdf.ln(15)
            pdf.set_font("Arial", 'I', 8)
            pdf.set_text_color(100, 100, 100)
            pdf.cell(0, 4, "* Precos e condicoes comerciais sujeitos a alteracao conforme disponibilidade de estoque.", 0, 1)
            pdf.cell(0, 4, "* Este documento e apenas uma cotacao/orcamento, nao possuindo valor fiscal.", 0, 1)
            
            return bytes(pdf.output())

        with col_act2:
            pdf_bytes = gerar_pdf(st.session_state.orcamento_itens, nome_cliente_final, total_orcamento)
            st.download_button(
                label="📄 Baixar Orçamento em PDF Profissional",
                data=pdf_bytes,
                file_name=f"Orcamento_{nome_cliente_final.replace(' ', '_')}_{datetime.now().strftime('%d%m%Y')}.pdf",
                mime="application/pdf",
                use_container_width=True
            )

# ABA 3: Orçamentos Salvos no Sistema
with tab3:
    st.subheader("📂 Orçamentos Salvos no Sistema")
    conn = get_db_connection()
    df_salvos = pd.read_sql_query("SELECT id, cliente, data, total FROM orcamentos ORDER BY id DESC", conn)
    conn.close()
    
    if df_salvos.empty:
        st.info("Nenhum orçamento salvo até o momento.")
    else:
        st.dataframe(df_salvos, use_container_width=True)
        
        orc_id_reabrir = st.selectbox("Selecione um orçamento anterior para reabrir:", options=df_salvos['id'].tolist(), format_func=lambda x: f"Orçamento #{x} - {df_salvos[df_salvos['id'] == x]['cliente'].values[0]} (R$ {df_salvos[df_salvos['id'] == x]['total'].values[0]:.2f})")
        
        if st.button("🔄 Reabrir Itens deste Orçamento na Aba Atual", use_container_width=True):
            conn = get_db_connection()
            orc_row = conn.execute("SELECT cliente, itens_json FROM orcamentos WHERE id = ?", (orc_id_reabrir,)).fetchone()
            conn.close()
            if orc_row:
                st.session_state.orcamento_itens = json.loads(orc_row['itens_json'])
                st.session_state.nome_cliente = orc_row['cliente']
                st.toast("✅ Orçamento carregado na aba Orçamento Atual!")
                st.rerun()

# ABA 4: Histórico Geral de Produtos
with tab4:
    st.subheader("4. Histórico de Medicamentos Cadastrados")
    conn = get_db_connection()
    df_view = pd.read_sql_query("SELECT id, codigo, nome, fornecedor, custo_unitario, margem_lucro, preco_venda, data_entrada FROM produtos ORDER BY id DESC", conn)
    conn.close()
    
    if not df_view.empty:
        st.dataframe(df_view, use_container_width=True)
    else:
        st.info("Nenhum dado cadastrado.")
