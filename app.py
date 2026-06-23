import streamlit as st
import pandas as pd
import math
from fpdf import FPDF
import tempfile
import os
import base64
from datetime import datetime

# ------------------------------------------------------------
# Configuración
# ------------------------------------------------------------
st.set_page_config(page_title="Modelagua - Análisis Básico", page_icon="💧", layout="wide")

if 'muestras_procesadas' not in st.session_state:
    st.session_state.muestras_procesadas = 0

# ------------------------------------------------------------
# Funciones de análisis (sin cambios)
# ------------------------------------------------------------
def convertir_a_mg_L(valor, unidad, parametro):
    """Convierte cualquier concentración a mg/L"""
    if unidad == 'mg/L' or unidad == 'ppm':
        return valor
    elif unidad == 'meq/L':
        pesos_eq = {
            'Ca': 40.08/2, 'Mg': 24.31/2, 'Na': 22.99/1, 'K': 39.10/1,
            'HCO3': 61.02/1, 'SO4': 96.06/2, 'Cl': 35.45/1
        }
        eq = pesos_eq.get(parametro, 1)
        return valor * eq
    elif unidad == 'µg/L':
        return valor / 1000.0
    else:
        return valor

def balance_ionico(datos_mg):
    pesos = {'Ca':40.08, 'Mg':24.31, 'Na':22.99, 'K':39.10, 'HCO3':61.02, 'SO4':96.06, 'Cl':35.45}
    valencias = {'Ca':2, 'Mg':2, 'Na':1, 'K':1, 'HCO3':1, 'SO4':2, 'Cl':1}
    meq = {ion: (datos_mg.get(ion, 0) * valencias[ion]) / pesos[ion] for ion in pesos}
    cationes = meq['Ca'] + meq['Mg'] + meq['Na'] + meq['K']
    aniones = meq['HCO3'] + meq['SO4'] + meq['Cl']
    if cationes + aniones == 0:
        error = 0
    else:
        error = (cationes - aniones) / (cationes + aniones) * 100
    if abs(error) < 5:
        diag = "[OK] Balance correcto (<5%)"
    elif abs(error) < 10:
        diag = "[!] Balance aceptable (5-10%)"
    else:
        diag = "[ERROR] Balance deficiente (>10%)"
        diag += " - Exceso de cationes" if cationes > aniones else " - Exceso de aniones"
    return meq, cationes, aniones, error, diag

def kurlov(meq):
    suma_cat = meq['Ca']+meq['Mg']+meq['Na']+meq['K']
    suma_an = meq['HCO3']+meq['SO4']+meq['Cl']
    if suma_cat == 0 or suma_an == 0:
        return "Datos insuficientes"
    porc_cat = {ion: meq[ion]/suma_cat*100 for ion in ['Ca','Mg','Na','K']}
    porc_an = {ion: meq[ion]/suma_an*100 for ion in ['HCO3','SO4','Cl']}
    cationes = [ion for ion in ['Na','Ca','Mg','K'] if porc_cat.get(ion,0) >= 20]
    aniones = [ion for ion in ['HCO3','SO4','Cl'] if porc_an.get(ion,0) >= 20]
    simb = {'HCO3':'HCO3', 'SO4':'SO4', 'Cl':'Cl', 'Na':'Na', 'Ca':'Ca', 'Mg':'Mg', 'K':'K'}
    return " · ".join([simb[a] for a in aniones]) + " – " + " · ".join([simb[c] for c in cationes])

def relaciones_ionicas(meq):
    Na_Cl = meq['Na'] / meq['Cl'] if meq['Cl'] != 0 else 0
    Ca_Mg = meq['Ca'] / meq['Mg'] if meq['Mg'] != 0 else 0
    CaMg_HCO3 = (meq['Ca']+meq['Mg']) / meq['HCO3'] if meq['HCO3'] != 0 else 0
    interp = []
    if Na_Cl > 1.2:
        interp.append(f"Na/Cl={Na_Cl:.2f} >1.2 → Exceso de sodio (intercambio iónico o silicatos)")
    elif Na_Cl < 0.8:
        interp.append(f"Na/Cl={Na_Cl:.2f} <0.8 → Posible influencia marina")
    else:
        interp.append(f"Na/Cl={Na_Cl:.2f} → Disolución de halita")
    if Ca_Mg > 2:
        interp.append(f"Ca/Mg={Ca_Mg:.2f} >2 → Influencia de calcita")
    elif Ca_Mg < 1:
        interp.append(f"Ca/Mg={Ca_Mg:.2f} <1 → Influencia de dolomita o aguas marinas")
    else:
        interp.append(f"Ca/Mg={Ca_Mg:.2f} → Mezcla calcita-dolomita")
    if CaMg_HCO3 < 0.5:
        interp.append(f"(Ca+Mg)/HCO3={CaMg_HCO3:.2f} <0.5 → Exceso HCO3 (CO2 profundo o silicatos)")
    elif CaMg_HCO3 > 1:
        interp.append(f"(Ca+Mg)/HCO3={CaMg_HCO3:.2f} >1 → Exceso Ca+Mg (disolución carbonatos)")
    else:
        interp.append(f"(Ca+Mg)/HCO3={CaMg_HCO3:.2f} → Equilibrio carbonatado")
    return Na_Cl, Ca_Mg, CaMg_HCO3, interp

def indice_langelier(pH, temp_c, alcalinidad_caco3, calcio_mg, tds):
    try:
        if tds <= 0 or calcio_mg <= 0 or alcalinidad_caco3 <= 0 or pH is None:
            return None
        A = (math.log10(tds) - 1) / 10
        B = -13.12 * math.log10(temp_c + 273) + 34.55
        C = math.log10(calcio_mg) - 0.4
        D = math.log10(alcalinidad_caco3)
        pHs = (9.3 + A + B) - (C + D)
        return pH - pHs
    except:
        return None

def clean_text(txt):
    replacements = {'→': '->', '–': '-', '₃': '3', '₂': '2', '₄': '4', '°': '°', '·': '.',
                    'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ñ': 'n', 'ü': 'u',
                    'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U', 'Ñ': 'N', 'Ü': 'U'}
    for src, dst in replacements.items():
        txt = txt.replace(src, dst)
    return txt.encode('ascii', 'ignore').decode('ascii')

def generar_informe(datos_mg, temperatura_c, ph, nombre_muestra="Muestra", ce_val=None, eh_val=None):
    # Solo los mayoritarios para el balance y relaciones
    mayoritarios = {k: datos_mg.get(k, 0) for k in ['Ca', 'Mg', 'Na', 'K', 'HCO3', 'SO4', 'Cl']}
    meq, cat, an, error, diag_balance = balance_ionico(mayoritarios)
    tipo = kurlov(meq)
    na_cl, ca_mg, caMg_hco3, interps = relaciones_ionicas(meq)
    tds = sum(mayoritarios.values()) + datos_mg.get('SiO2', 0)
    if tds < 500: clasif_tds = "Dulce"
    elif tds < 1500: clasif_tds = "Salobre"
    elif tds < 5000: clasif_tds = "Salina"
    else: clasif_tds = "Salmuera"
    hco3_mg = mayoritarios.get('HCO3', 0)
    alcalinidad_caco3 = (hco3_mg / 61.02) * 50 if hco3_mg > 0 else 0
    if ph is not None and ph > 0:
        li = indice_langelier(ph, temperatura_c, alcalinidad_caco3, mayoritarios.get('Ca',0), tds)
        if li is not None:
            if li > 0: riesgo = f"LI = {li:.2f} → Sobresaturada. Riesgo de incrustación."
            elif li < 0: riesgo = f"LI = {li:.2f} → Subsaturada. Riesgo de corrosión."
            else: riesgo = f"LI = {li:.2f} → Equilibrio."
        else:
            riesgo = "No se pudo calcular LI"
    else:
        riesgo = "No se calculó LI (falta pH)"
    
    lines = []
    lines.append(f"\n--- INFORME PARA {nombre_muestra} ---")
    lines.append("\n1. CALIDAD DE LOS DATOS")
    lines.append(f"   Error de balance: {error:.2f}%")
    lines.append(f"   {diag_balance}")
    lines.append("\n2. CLASIFICACIÓN HIDROQUÍMICA")
    lines.append(f"   Tipo Kurlov: {tipo}")
    lines.append(f"   TDS: {tds:.0f} mg/L → {clasif_tds}")
    lines.append("\n3. RELACIONES IÓNICAS")
    lines.append(f"   Na/Cl = {na_cl:.2f}")
    lines.append(f"   Ca/Mg = {ca_mg:.2f}")
    lines.append(f"   (Ca+Mg)/HCO3 = {caMg_hco3:.2f}")
    lines.append("   Interpretación:")
    for line in interps:
        lines.append(f"      • {line}")
    lines.append("\n4. RIESGO DE INCRUSTACIÓN (CALCITA)")
    lines.append(f"   {riesgo}")
    
    # Añadir información adicional si está disponible
    if ce_val is not None:
        lines.append(f"\n📊 Conductividad eléctrica: {ce_val:.1f} µS/cm")
    if eh_val is not None:
        lines.append(f"⚡ Potencial redox: {eh_val:.1f} mV")
    
    # Mostrar minoritarios si existen
    minoritarios = {k: v for k, v in datos_mg.items() if k not in ['Ca', 'Mg', 'Na', 'K', 'HCO3', 'SO4', 'Cl']}
    if minoritarios:
        lines.append("\n📌 Elementos traza (mg/L):")
        for k, v in minoritarios.items():
            if v > 0:
                lines.append(f"   {k}: {v:.3f}")
    
    return "\n".join(lines)

def generar_pdf(lista_informes, resumen_final, lista_resumen):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font('Courier', '', 9)
    for nombre, info in lista_informes:
        pdf.set_font('Courier', 'B', 11)
        pdf.cell(0, 8, clean_text(f"MUESTRA: {nombre}"), 0, 1, 'L')
        pdf.set_font('Courier', '', 9)
        for line in info.split('\n'):
            pdf.cell(0, 5, clean_text(line), 0, 1, 'L')
        pdf.add_page()
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, clean_text("RESUMEN COMPARATIVO"), 0, 1, 'C')
    pdf.ln(8)
    pdf.set_font('Arial', '', 11)
    for line in resumen_final.strip().split('\n'):
        pdf.multi_cell(0, 6, clean_text(line))
        pdf.ln(2)
    pdf.ln(5)
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 8, clean_text("Tabla resumen por muestra"), 0, 1, 'L')
    pdf.set_font('Arial', '', 10)
    pdf.cell(40, 8, clean_text("Muestra"), 1)
    pdf.cell(50, 8, clean_text("TDS (mg/L)"), 1)
    pdf.cell(100, 8, clean_text("Tipo Kurlov"), 1)
    pdf.ln()
    for nombre, tds, tipo in lista_resumen:
        pdf.cell(40, 8, clean_text(nombre), 1)
        pdf.cell(50, 8, str(int(tds)), 1)
        pdf.cell(100, 8, clean_text(tipo), 1)
        pdf.ln()
    return pdf

# ------------------------------------------------------------
# Interfaz
# ------------------------------------------------------------
st.title("💧 Modelagua - Análisis Básico")
st.markdown("""
**Bienvenido al análisis básico gratuito.**  
Puedes subir un archivo (CSV o Excel) o ingresar los datos manualmente.  
**Límite:** 3 muestras por sesión (no se guarda información personal).
""")
st.info(f"📊 Muestras procesadas en esta sesión: **{st.session_state.muestras_procesadas} de 3** (plan gratuito).")

def descargar_plantilla():
    plantilla = pd.DataFrame({
        'Ca': [23],
        'Mg': [8],
        'Na': [580],
        'K': [30],
        'HCO3': [842],
        'SO4': [534],
        'Cl': [236],
        'pH': [7.7],
        'Temp.(oC)': [50],
        'SiO2': [98.65],
        'As': [0.1],
        'B': [6.9],
        'Li': [1.6],
        'Mn': [0.1],
        'Fe': [0.0],
        'Al': [0.1],
        'Sr': [1.7]
    })
    csv = plantilla.to_csv(index=False)
    b64 = base64.b64encode(csv.encode()).decode()
    return f'<a href="data:file/csv;base64,{b64}" download="plantilla_modelagua.csv">📥 Descargar plantilla de ejemplo (.csv)</a>'

st.markdown(descargar_plantilla(), unsafe_allow_html=True)

with st.expander("📖 Guía de formato del archivo"):
    st.markdown(
        "**Columnas sugeridas (nombres exactos):**\n"
        "- `Ca`, `Mg`, `Na`, `K`, `HCO3`, `SO4`, `Cl` (mayoritarios)\n"
        "- `SiO2`, `As`, `B`, `Li`, `Mn`, `Fe`, `Al`, `Sr` (minoritarios, opcionales)\n"
        "- `pH`, `Temp.(oC)` (fisicoquímicos, opcionales)\n\n"
        "**Unidades aceptadas:** mg/L (por defecto), meq/L, ppm, µg/L.\n\n"
        "**Ejemplo de fila (CSV):**\n"
        "```\n"
        "Ca,Mg,Na,K,HCO3,SO4,Cl,pH,Temp.(oC),SiO2,As,B,Li,Mn,Fe,Al,Sr\n"
        "23,8,580,30,842,534,236,7.7,50,98.65,0.1,6.9,1.6,0.1,0,0.1,1.7\n"
        "```\n"
        "- Si falta algún valor, escribe `0` o deja la celda vacía.\n"
        "- No uses puntos o comas para separar miles (ej. `580` en lugar de `580.0`).\n"
        "- Si tu archivo tiene más columnas, la app las ignorará."
    )

opcion = st.radio("¿Cómo quieres ingresar los datos?", ("📁 Subir archivo", "✏️ Ingreso manual"))

# ------------------------------------------------------------
# SUBIR ARCHIVO (versión flexible)
# ------------------------------------------------------------
if opcion == "📁 Subir archivo":
    archivo = st.file_uploader("Selecciona un archivo (CSV o Excel)", type=["csv", "xlsx"])
    if archivo is not None:
        try:
            if archivo.name.endswith('.csv'):
                codificaciones = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
                df = None
                for enc in codificaciones:
                    try:
                        archivo.seek(0)
                        df = pd.read_csv(archivo, encoding=enc)
                        break
                    except UnicodeDecodeError:
                        continue
                if df is None:
                    st.error("No se pudo leer el archivo CSV. Intenta guardarlo como UTF-8 desde Excel.")
                    st.stop()
            else:
                df = pd.read_excel(archivo, engine='openpyxl')

            st.write("Vista previa de las primeras filas:")
            st.dataframe(df.head())

            todas_columnas = list(df.columns)

            # ------------------------------------------------------------------
            # 1. PARÁMETROS FISICOQUÍMICOS
            # ------------------------------------------------------------------
            st.subheader("📊 Parámetros fisicoquímicos")
            col1, col2 = st.columns(2)

            with col1:
                col_muestra = st.selectbox("Columna con ID de muestra", ["Ninguna"] + todas_columnas, index=0)
                col_temp = st.selectbox("Columna con Temperatura (°C)", ["No disponible"] + todas_columnas, index=0)
                col_ph = st.selectbox("Columna con pH", ["No disponible"] + todas_columnas, index=0)

            with col2:
                col_ce = st.selectbox("Columna con Conductividad (CE)", ["No disponible"] + todas_columnas, index=0)
                if col_ce != "No disponible":
                    unidad_ce = st.selectbox("Unidad de CE", ["µS/cm", "mS/cm", "dS/m"], key="ce_unit")
                else:
                    unidad_ce = None

                col_eh = st.selectbox("Columna con Potencial redox (Eh)", ["No disponible"] + todas_columnas, index=0)
                if col_eh != "No disponible":
                    unidad_eh = st.selectbox("Unidad de Eh", ["mV", "V"], key="eh_unit")
                else:
                    unidad_eh = None

            # ------------------------------------------------------------------
            # 2. PARÁMETROS QUÍMICOS (CONCENTRACIONES)
            # ------------------------------------------------------------------
            st.subheader("🧪 Parámetros químicos (concentraciones)")

            parametros = {
                'Ca': ['mg/L', 'meq/L', 'ppm'],
                'Mg': ['mg/L', 'meq/L', 'ppm'],
                'Na': ['mg/L', 'meq/L', 'ppm'],
                'K': ['mg/L', 'meq/L', 'ppm'],
                'HCO3': ['mg/L', 'meq/L', 'ppm'],
                'SO4': ['mg/L', 'meq/L', 'ppm'],
                'Cl': ['mg/L', 'meq/L', 'ppm'],
                'SiO2': ['mg/L', 'µg/L', 'ppm'],
                'As': ['mg/L', 'µg/L', 'ppm'],
                'B': ['mg/L', 'µg/L', 'ppm'],
                'Li': ['mg/L', 'µg/L', 'ppm'],
                'Mn': ['mg/L', 'µg/L', 'ppm'],
                'Fe': ['mg/L', 'µg/L', 'ppm'],
                'Al': ['mg/L', 'µg/L', 'ppm'],
                'Sr': ['mg/L', 'µg/L', 'ppm'],
            }

            seleccion_columnas = {}
            seleccion_unidades = {}

            cols_param = st.columns(3)
            for i, (param, unidades) in enumerate(parametros.items()):
                with cols_param[i % 3]:
                    st.markdown(f"**{param}**")
                    columna = st.selectbox(f"Columna para {param}", ["No disponible"] + todas_columnas, key=f"col_{param}")
                    seleccion_columnas[param] = columna
                    if columna != "No disponible":
                        unidad = st.selectbox(f"Unidad de {param}", unidades, key=f"unidad_{param}")
                        seleccion_unidades[param] = unidad
                    else:
                        seleccion_unidades[param] = None

            # ------------------------------------------------------------------
            # 3. PROCESAMIENTO
            # ------------------------------------------------------------------
            if st.button("🔬 Procesar"):
                if st.session_state.muestras_procesadas >= 3:
                    st.error("⚠️ Límite gratuito alcanzado. Contacta para plan de pago.")
                else:
                    mayoritarios_seleccionados = [p for p in ['Ca', 'Mg', 'Na', 'K', 'HCO3', 'SO4', 'Cl'] if seleccion_columnas[p] != "No disponible"]
                    if len(mayoritarios_seleccionados) < 3:
                        st.error("❌ Debes seleccionar al menos 3 iones mayoritarios (Ca, Mg, Na, K, HCO3, SO4, Cl).")
                        st.stop()

                    num_muestras = len(df)
                    if st.session_state.muestras_procesadas + num_muestras > 3:
                        restantes = 3 - st.session_state.muestras_procesadas
                        st.warning(f"⚠️ El archivo tiene {num_muestras} muestras. Solo puedes procesar {restantes} más.")
                    else:
                        lista_informes = []
                        lista_resumen = []

                        for idx, row in df.iterrows():
                            if col_muestra != "Ninguna":
                                nombre = str(row[col_muestra])
                                if pd.isna(nombre) or nombre == '':
                                    nombre = f"Muestra_{idx+1}"
                            else:
                                nombre = f"Muestra_{idx+1}"

                            # Temperatura
                            if col_temp != "No disponible":
                                temp = row[col_temp]
                                if pd.isna(temp):
                                    temp = 25.0
                            else:
                                temp = 25.0

                            # pH
                            if col_ph != "No disponible":
                                ph = row[col_ph]
                                if pd.isna(ph):
                                    ph = None
                            else:
                                ph = None

                            # Conductividad
                            ce_val = None
                            if col_ce != "No disponible":
                                ce_val = row[col_ce]
                                if not pd.isna(ce_val):
                                    if unidad_ce == "mS/cm":
                                        ce_val = ce_val * 1000
                                    elif unidad_ce == "dS/m":
                                        ce_val = ce_val * 1000
                                else:
                                    ce_val = None

                            # Eh
                            eh_val = None
                            if col_eh != "No disponible":
                                eh_val = row[col_eh]
                                if not pd.isna(eh_val):
                                    if unidad_eh == "V":
                                        eh_val = eh_val * 1000
                                else:
                                    eh_val = None

                            # Concentraciones
                            datos_mg = {}
                            for param in parametros:
                                columna = seleccion_columnas[param]
                                if columna != "No disponible":
                                    val = row[columna]
                                    if pd.isna(val):
                                        val = 0
                                    unidad = seleccion_unidades[param]
                                    datos_mg[param] = convertir_a_mg_L(val, unidad, param)
                                else:
                                    datos_mg[param] = 0

                            info = generar_informe(datos_mg, temp, ph, nombre, ce_val, eh_val)
                            lista_informes.append((nombre, info))
                            tds = sum([datos_mg[p] for p in ['Ca', 'Mg', 'Na', 'K', 'HCO3', 'SO4', 'Cl']]) + datos_mg.get('SiO2', 0)
                            meq,_,_,_,_ = balance_ionico({p: datos_mg[p] for p in ['Ca', 'Mg', 'Na', 'K', 'HCO3', 'SO4', 'Cl']})
                            tipo = kurlov(meq)
                            lista_resumen.append((nombre, tds, tipo))

                        st.session_state.muestras_procesadas += num_muestras

                        resumen = """Balance iónico: Errores aceptables (<10%).
                        Clasificación Kurlov: Varía según muestra.
                        TDS: Rango salino o según cada muestra.
                        Relaciones iónicas: Exceso de sodio, mezcla calcita/dolomita, exceso HCO3.
                        Riesgo: Mayoría sobresaturada en calcita (incrustación), excepto si LI negativo (corrosión)."""

                        try:
                            pdf = generar_pdf(lista_informes, resumen, lista_resumen)
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                                pdf.output(tmp.name)
                                with open(tmp.name, "rb") as f:
                                    st.download_button("📥 Descargar informe PDF", f, file_name=f"informe_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
                                os.unlink(tmp.name)
                            st.success(f"✅ Procesado. Has usado {st.session_state.muestras_procesadas} de 3 muestras gratis.")
                        except Exception as e:
                            st.error(f"❌ Error al generar el PDF: {e}")

        except Exception as e:
            st.error(f"❌ Error al leer el archivo: {e}")

# ------------------------------------------------------------
# INGRESO MANUAL
# ------------------------------------------------------------
elif opcion == "✏️ Ingreso manual":
    st.subheader("Ingresa los valores de una muestra (unidad: mg/L)")
    nombre_manual = st.text_input("Nombre de la muestra (opcional)", value="Muestra_manual")
    cols = st.columns(2)
    datos_manual = {}
    with cols[0]:
        datos_manual['Ca'] = st.number_input("Ca (mg/L)", value=0.0, step=0.1)
        datos_manual['Mg'] = st.number_input("Mg (mg/L)", value=0.0, step=0.1)
        datos_manual['Na'] = st.number_input("Na (mg/L)", value=0.0, step=0.1)
        datos_manual['K'] = st.number_input("K (mg/L)", value=0.0, step=0.1)
        datos_manual['SiO2'] = st.number_input("SiO2 (mg/L)", value=0.0, step=0.1)
    with cols[1]:
        datos_manual['HCO3'] = st.number_input("HCO3 (mg/L)", value=0.0, step=0.1)
        datos_manual['SO4'] = st.number_input("SO4 (mg/L)", value=0.0, step=0.1)
        datos_manual['Cl'] = st.number_input("Cl (mg/L)", value=0.0, step=0.1)
        temp_man = st.number_input("Temperatura (°C)", value=25.0, step=0.1)
        ph_man = st.number_input("pH", value=7.0, step=0.01)

    if st.button("🔬 Generar informe", key="procesar_manual"):
        if st.session_state.muestras_procesadas >= 3:
            st.error("⚠️ Límite gratuito alcanzado. Contacta para plan de pago.")
        else:
            datos_mg = {k: v for k, v in datos_manual.items()}
            if sum(datos_mg.values()) == 0:
                st.warning("⚠️ Todos los valores son cero. Ingresa al menos un parámetro.")
            else:
                info = generar_informe(datos_mg, temp_man, ph_man, nombre_manual)
                st.text(info)
                lista_informes = [(nombre_manual, info)]
                tds = sum([datos_mg[p] for p in ['Ca', 'Mg', 'Na', 'K', 'HCO3', 'SO4', 'Cl']]) + datos_mg.get('SiO2', 0)
                meq,_,_,_,_ = balance_ionico({p: datos_mg[p] for p in ['Ca', 'Mg', 'Na', 'K', 'HCO3', 'SO4', 'Cl']})
                tipo = kurlov(meq)
                lista_resumen = [(nombre_manual, tds, tipo)]
                resumen = "Informe de una muestra manual."
                try:
                    pdf = generar_pdf(lista_informes, resumen, lista_resumen)
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        pdf.output(tmp.name)
                        with open(tmp.name, "rb") as f:
                            st.download_button("📥 Descargar PDF", f, file_name=f"informe_manual_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
                        os.unlink(tmp.name)
                    st.session_state.muestras_procesadas += 1
                    st.success(f"✅ Procesado. Has usado {st.session_state.muestras_procesadas} de 3 muestras gratis.")
                except Exception as e:
                    st.error(f"❌ Error al generar el PDF: {e}")

# ------------------------------------------------------------
# Pie de página
# ------------------------------------------------------------
st.markdown("---")
st.caption("Modelagua - Análisis hidrogeoquímico básico. Para servicios profesionales, contacta con nosotros.")
