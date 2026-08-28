import streamlit as st
import pandas as pd
import xmltodict
import sqlite3
import urllib.parse
from fpdf import FPDF

st.set_page_config(page_title="Gestão de Orçamentos Farmacêuticos", layout="wide")

# Conexão com banco local SQLite
conn = sqlite3.connect("farmacia.db", check_same_thread=False)

def init_db():
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS compras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chave_acesso TEXT,
                nfe_numero TEXT,
                data_emissao TEXT,
                fornecedor TEXT,
                codigo_produto TEXT,
                descricao TEXT,
                ncm TEXT,
                quantidade REAL,
                valor_unitario REAL,
                valor_total REAL,
                UNIQUE(chave_acesso, codigo_produto)
            )
        """)

init_db()

# Inicialização do carrinho
if 'carrinho' not in st.session_state:
    st.session_state.carrinho = []

def extrair_tag(dados, chave):
    if isinstance(dados, dict):
        for k, v in dados.items():
            if k.endswith(chave) or k == chave:
                return v
            res = extrair_tag(v, chave)
            if res is not None:
                return res
    elif isinstance(dados, list):
        for item in dados:
            res = extrair_tag(item, chave)
            if res is not None:
                return res
    return None

def processar_xml(xml_file):
    try:
        dados = xmltodict.parse(xml_file.getvalue(), process_namespaces=False)
        inf_nfe = extrair_tag(dados, 'infNFe')
        if not inf_nfe:
            return False, 0, "Estrutura 'infNFe' não encontrada."
            
        chave_acesso = str(inf_nfe.get('@Id', '')).replace('NFe', '')
        ide = inf_nfe.get('ide', {})
        emit = inf_nfe.get('emit', {})
        
        numero_nfe = str(ide.get('nNF', 'S/N'))
        data_emissao = str(ide.get('dhEmi', ide.get('dEmi', '')))[:10]
        fornecedor = str(emit.get('xNome', 'Desconhecido'))
        
        detalhes = inf_nfe.get('det', [])
        if isinstance(detalhes, dict):
            detalhes = [detalhes]
            
        itens = []
        for det in detalhes:
            prod = det.get('prod', {})
            itens.append((
                chave_acesso,
                numero_nfe,
                data_emissao,
                fornecedor,
                str(prod.get('cProd', '')),
                str(prod.get('xProd', '')),
                str(prod.get('NCM', '')),
                float(prod.get('qCom', 0) or 0),
                float(prod.get('vUnCom', 0) or 0),
                float(prod.get('vProd', 0) or 0)
            ))
            
        inseridos = 0
        with conn:
            for item in itens:
                cursor = conn.execute("""
                    INSERT OR IGNORE INTO compras (
                        chave_acesso, nfe_numero, data_emissao, fornecedor, 
                        codigo_produto, descricao, ncm, quantidade, valor_unitario, valor_total
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, item)
                if cursor.rowcount > 0:
                    inseridos += 1

        return True, inseridos, ""
    except Exception as e:
        return False, 0, str(e)

def gerar_links_pesquisa(termo):
    termo_limpo = " ".join([p for p in termo.split() if len(p) > 2][:4])
    termo_encoded = urllib.parse.quote_plus(termo_limpo)
    return {
        "Google Shopping": f"https://www.google.com/search?tbm=shop&q={termo_encoded}",
        "Consulta Remédios": f"https://consultaremedios.com.br/busca?termo={termo_encoded}",
        "Mercado Livre": f"https://lista.mercadolivre.com.br/{termo_encoded}",
        "Drogasil": f"https://www.drogasil.com.br/search?w={termo_encoded}",
        "Ultrafarma": f"https://www.ultrafarma.com.br/busca?q={termo_encoded}"
    }

def gerar_pdf(cliente, itens, total_venda):
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    # Título Principal
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(190, 10, "ORÇAMENTO DE MEDICAMENTOS E INSUMOS", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    
    # Cabeçalho do Cliente e Data
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(120, 6, f"Cliente: {cliente if cliente else 'Consumidor / Farmácia'}", align="L")
    pdf.cell(70, 6, f"Data: {pd.Timestamp.now().strftime('%d/%m/%Y %H:%M')}", align="R", new_x="LMARGIN", new_y="NEXT")
    
    # Linha divisória
    pdf.set_draw_color(180, 180, 180)
    pdf.line(10, pdf.get_y() + 2, 200, pdf.get_y() + 2)
    pdf.ln(6)
    
    # Cabeçalho da Tabela
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(90, 8, " Descrição", border=1, fill=True)
    pdf.cell(15, 8, "Unid", border=1, align="C", fill=True)
    pdf.cell(20, 8, "Qtd", border=1, align="C", fill=True)
    pdf.cell(32, 8, "Unitário (R$)", border=1, align="R", fill=True)
    pdf.cell(33, 8, "Total (R$)", border=1, align="R", fill=True, new_x="LMARGIN", new_y="NEXT")
    
    # Itens do Orçamento
    pdf.set_font("Helvetica", "", 9)
    for item in itens:
        nome_prod = " " + ((item['produto'][:42] + '..') if len(item['produto']) > 45 else item['produto'])
        qtd_formatada = f"{int(item['quantidade']):,}".replace(",", ".") if float(item['quantidade']).is_integer() else f"{item['quantidade']:.2f}"
        
        pdf.cell(90, 7, nome_prod, border=1)
        pdf.cell(15, 7, item.get('unidade', 'UN'), border=1, align="C")
        pdf.cell(20, 7, qtd_formatada, border=1, align="C")
        pdf.cell(32, 7, f"R$ {item['preco_venda_unit']:.2f} ", border=1, align="R")
        pdf.cell(33, 7, f"R$ {item['total_item']:.2f} ", border=1, align="R", new_x="LMARGIN", new_y="NEXT")
        
    pdf.ln(4)
    
    # Total Geral
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(157, 9, "VALOR TOTAL DO ORÇAMENTO: ", align="R")
    pdf.set_fill_color(230, 242, 255)
    pdf.cell(33, 9, f"R$ {total_venda:.2f} ", border=1, align="R", fill=True, new_x="LMARGIN", new_y="NEXT")
    
    return bytes(pdf.output())

# --- MENU LATERAL ---
with st.sidebar:
    st.header("📥 Importação de Notas")
    arquivos_xml = st.file_uploader("Suba os arquivos XML", type=["xml"], accept_multiple_files=True)
    if st.button("Processar Arquivos") and arquivos_xml:
        total_novos = 0
        erros = []
        for f in arquivos_xml:
            sucesso, novos, erro = processar_xml(f)
            if sucesso:
                total_novos += novos
            else:
                erros.append(f"{f.name}: {erro}")
                
        if total_novos > 0:
            st.success(f"{total_novos} novos itens adicionados ao banco!")
        else:
            st.info("Nenhum item novo adicionado (notas já importadas).")
            
        if erros:
            for erro in erros:
                st.error(erro)
                
    st.divider()
    with st.expander("✍️ Cadastrar Preço Manual no Banco"):
        with st.form("form_manual"):
            prod_manual = st.text_input("Nome do Produto:")
            forn_manual = st.text_input("Fornecedor / Origem:", value="Entrada Manual")
            custo_manual = st.number_input("Custo Unitário (R$):", min_value=0.01, value=1.00, step=0.10)
            btn_salvar_manual = st.form_submit_button("Salvar no Banco")
            
            if btn_salvar_manual and prod_manual:
                data_hoje = pd.Timestamp.now().strftime('%Y-%m-%d')
                chave_fake = f"MANUAL_{pd.Timestamp.now().strftime('%Y%m%d%H%M%S')}"
                with conn:
                    conn.execute("""
                        INSERT INTO compras (chave_acesso, nfe_numero, data_emissao, fornecedor, codigo_produto, descricao, ncm, quantidade, valor_unitario, valor_total)
                        VALUES (?, 'MANUAL', ?, ?, 'MANUAL', ?, '00000000', 1, ?, ?)
                    """, (chave_fake, data_hoje, forn_manual, prod_manual.upper(), custo_manual, custo_manual))
                st.success("Item manual cadastrado com sucesso!")
                st.rerun()

st.title("💊 Sistema de Gestão de Custos e Orçamentos")

tab_busca, tab_orcamento, tab_banco = st.tabs(["🔍 Inserir Produto no Orçamento", "📋 Orçamento Atual", "🗄️ Histórico Completo"])

# --- ABA 1: INSERIR PRODUTO ---
with tab_busca:
    st.subheader("1. Inserir Produto no Orçamento")
    
    tipo_insercao = st.radio("Origem do Produto:", ["📦 Buscar nas Notas Fiscais (XML)", "✍️ Digitar Item Avulso / Manual"], horizontal=True)
    
    if tipo_insercao == "📦 Buscar nas Notas Fiscais (XML)":
        produtos_unicos = pd.read_sql_query("SELECT DISTINCT descricao FROM compras ORDER BY descricao", conn)['descricao'].tolist()
        
        selecionado = st.selectbox("Selecione ou digite o medicamento:", [""] + produtos_unicos)
        
        if selecionado:
            nome_final = selecionado
            df_historico = pd.read_sql_query("""
                SELECT data_emissao AS "Data", fornecedor AS "Fornecedor", quantidade AS "Qtd Comprada", valor_unitario AS "Custo Unit. (R$)"
                FROM compras 
                WHERE descricao = ?
                ORDER BY data_emissao DESC
            """, conn, params=[selecionado])
            
            st.write("**Histórico de Compras (XMLs):**")
            st.dataframe(df_historico.style.format({
                "Qtd Comprada": "{:,.0f}".format,
                "Custo Unit. (R$)": "R$ {:.2f}".format
            }), use_container_width=True)
            
            ultimo_custo_sugerido = float(df_historico.iloc[0]['Custo Unit. (R$)'])
            
            # Links de Pesquisa Web
            with st.expander("🌐 Pesquisar Preço Geral na Internet (1 Clique)", expanded=False):
                termo_web = st.text_input("Termo de pesquisa:", value=selecionado)
                links = gerar_links_pesquisa(termo_web)
                
                col_l1, col_l2, col_l3, col_l4, col_l5 = st.columns(5)
                col_l1.link_button("🛍️ Google Shopping", links["Google Shopping"])
                col_l2.link_button("💊 Consulta Remédios", links["Consulta Remédios"])
                col_l3.link_button("📦 Mercado Livre", links["Mercado Livre"])
                col_l4.link_button("🔴 Drogasil", links["Drogasil"])
                col_l5.link_button("🔵 Ultrafarma", links["Ultrafarma"])
        else:
            nome_final = ""
            ultimo_custo_sugerido = 0.00
            
    else:
        # Modo Manual Avulso
        nome_final = st.text_input("Nome do Produto / Medicamento:", placeholder="Ex: TYLENOL 750MG COMPRIMIDOS").upper()
        ultimo_custo_sugerido = 1.00

    if nome_final:
        st.write("---")
        st.write("### 📦 Como você vai vender este item?")
        
        modo_conversao = st.radio(
            "Selecione o formato da venda:",
            [
                "🟢 Preço Direto (Sem conversão - o custo já é por unidade/caixa)",
                "🔵 Multiplicar (O custo registrado é unitário, mas vou vender a Caixa Fechada)",
                "🟠 Dividir (O custo registrado é da Caixa Fechada, mas vou vender Fracionado/Unidade)"
            ]
        )
        
        col_c1, col_c2, col_c3 = st.columns(3)
        
        with col_c1:
            custo_base_input = st.number_input(
                "Custo de Origem (R$):", 
                min_value=0.01, 
                value=ultimo_custo_sugerido, 
                step=0.10, 
                format="%.2f",
                help="Valor que veio na nota fiscal ou valor de compra de referência."
            )
            
        with col_c2:
            if "Multiplicar" in modo_conversao:
                unidade = "CX"
                fator = st.number_input("Quantas unidades vêm dentro da Caixa?", min_value=1.0, value=100.0, step=10.0)
                custo_final_calculado = custo_base_input * fator
                st.info(f"💡 Cálculo: R$ {custo_base_input:.2f} × {int(fator)} un = **R$ {custo_final_calculado:.2f} por Caixa**")
                
            elif "Dividir" in modo_conversao:
                unidade = "UN"
                fator = st.number_input("Quantas unidades vêm dentro da Caixa para dividir?", min_value=1.0, value=100.0, step=10.0)
                custo_final_calculado = custo_base_input / fator
                st.info(f"💡 Cálculo: R$ {custo_base_input:.2f} ÷ {int(fator)} un = **R$ {custo_final_calculado:.2f} por Unidade**")
                
            else:
                fator = 1.0
                custo_final_calculado = custo_base_input
                unidade = st.selectbox("Unidade:", ["UN", "CX", "CART", "AMP", "FR", "PCT"])
                st.info(f"💡 Custo mantido direto em **R$ {custo_final_calculado:.2f} por {unidade}**")

        with col_c3:
            st.metric("Custo Base de Venda", f"R$ {custo_final_calculado:.2f}", f"Unidade: {unidade}")

        st.write("---")
        st.write("### 💰 Margem e Quantidade de Venda")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            margem = st.number_input("Margem de Lucro Desejada (%)", min_value=0.0, value=25.0, step=1.0)
            preco_venda_unit = custo_final_calculado * (1 + margem / 100)
            st.caption(f"Preço de venda unitário: **R$ {preco_venda_unit:.2f}**")
            
        with col2:
            qtd_venda = st.number_input(f"Quantidade a Vender ({unidade}):", min_value=1.0, value=10.0, step=1.0)
            
        with col3:
            total_item = preco_venda_unit * qtd_venda
            st.metric("Valor Total deste Item", f"R$ {total_item:.2f}")
            
        if st.button("➕ Adicionar ao Orçamento"):
            nome_item_formatado = f"{nome_final} (CX C/{int(fator)})" if ("Multiplicar" in modo_conversao and fator > 1) else nome_final
            
            st.session_state.carrinho.append({
                "produto": nome_item_formatado,
                "unidade": unidade,
                "custo_unit": custo_final_calculado,
                "margem": margem,
                "preco_venda_unit": preco_venda_unit,
                "quantidade": qtd_venda,
                "total_custo": custo_final_calculado * qtd_venda,
                "total_item": total_item
            })
            st.success(f"'{nome_item_formatado}' adicionado com sucesso ao orçamento!")

# --- ABA 2: ORÇAMENTO COMPLETO ---
with tab_orcamento:
    st.subheader("2. Visualização e Exportação do Orçamento")
    
    if st.session_state.carrinho:
        cliente = st.text_input("Nome do Cliente / Farmácia:", placeholder="Ex: Farmácia Santa Luzia - Interior")
        
        df_carrinho = pd.DataFrame(st.session_state.carrinho)
        
        col_exibir = df_carrinho[["produto", "unidade", "quantidade", "custo_unit", "margem", "preco_venda_unit", "total_item"]].copy()
        col_exibir.columns = ["Produto", "Unid", "Qtd", "Custo (R$)", "Margem (%)", "Unit. Venda (R$)", "Subtotal (R$)"]
        
        st.dataframe(col_exibir.style.format({
            "Qtd": "{:,.0f}".format,
            "Custo (R$)": "R$ {:.2f}".format,
            "Margem (%)": "{:.1f}%".format,
            "Unit. Venda (R$)": "R$ {:.2f}".format,
            "Subtotal (R$)": "R$ {:.2f}"
        }), use_container_width=True)
        
        total_venda = df_carrinho['total_item'].sum()
        total_custo = df_carrinho['total_custo'].sum()
        lucro_estimado = total_venda - total_custo
        
        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("Total do Pedido", f"R$ {total_venda:.2f}")
        col_m2.metric("Custo Total", f"R$ {total_custo:.2f}")
        col_m3.metric("Lucro Estimado", f"R$ {lucro_estimado:.2f}")
        
        st.write("---")
        st.write("**Gerenciar Itens:**")
        cols_rem = st.columns([3, 1])
        with cols_rem[0]:
            idx_remover = st.selectbox(
                "Selecione um item para remover se necessário:",
                range(len(st.session_state.carrinho)),
                format_func=lambda i: f"{st.session_state.carrinho[i]['produto']} ({int(st.session_state.carrinho[i]['quantidade'])} {st.session_state.carrinho[i]['unidade']})"
            )
        with cols_rem[1]:
            st.write("")
            st.write("")
            if st.button("❌ Remover Item"):
                st.session_state.carrinho.pop(idx_remover)
                st.rerun()

        st.write("---")
        col_act1, col_act2 = st.columns(2)
        
        with col_act1:
            pdf_bytes = gerar_pdf(cliente, st.session_state.carrinho, total_venda)
            st.download_button(
                label="📄 Baixar Orçamento em PDF",
                data=pdf_bytes,
                file_name=f"Orcamento_{cliente.replace(' ', '_') if cliente else 'Farmacia'}.pdf",
                mime="application/pdf"
            )
            
        with col_act2:
            if st.button("🗑️ Limpar Todo o Orçamento"):
                st.session_state.carrinho = []
                st.rerun()
                
        # Texto WhatsApp
        st.write("**Texto formatado para WhatsApp:**")
        texto_whats = f"*ORÇAMENTO: {cliente if cliente else 'FARMÁCIA'}*\n\n"
        for item in st.session_state.carrinho:
            qtd_txt = f"{int(item['quantidade']):,}".replace(",", ".") if float(item['quantidade']).is_integer() else f"{item['quantidade']:.2f}"
            texto_whats += f"▪ {item['produto']}\n  Qtd: {qtd_txt} {item['unidade']} | Un: R$ {item['preco_venda_unit']:.2f} | Subtotal: R$ {item['total_item']:.2f}\n"
        texto_whats += f"\n*TOTAL: R$ {total_venda:.2f}*"
        
        st.text_area("Copiar e colar:", texto_whats, height=150)
    else:
        st.info("Nenhum item adicionado ao orçamento ainda. Vá na aba 'Inserir Produto no Orçamento'.")

# --- ABA 3: BANCO DE DADOS COMPLETO ---
with tab_banco:
    st.subheader("3. Itens Cadastrados no Banco")
    df_todos = pd.read_sql_query("""
        SELECT data_emissao AS "Data", fornecedor AS "Fornecedor", codigo_produto AS "Código", 
               descricao AS "Produto", valor_unitario AS "Custo Unit. (R$)", quantidade AS "Qtd"
        FROM compras 
        ORDER BY id DESC
    """, conn)
    
    if not df_todos.empty:
        st.write(f"Total de registros: **{len(df_todos)}**")
        st.dataframe(df_todos.style.format({
            "Qtd": "{:,.0f}".format,
            "Custo Unit. (R$)": "R$ {:.2f}".format
        }), use_container_width=True)
    else:
        st.info("Nenhum item no banco.")