# Copia del archivo principal para despliegue en Render
# (mismo contenido que ../streamlit_app.py)

import os
import tempfile
from io import BytesIO

import pandas as pd
import streamlit as st
import tabula

st.set_page_config(layout="wide")

# ------------------------------
# Simple username/password auth
# ------------------------------
USER_CREDENTIALS = {
    "admin": "admin"
}
# USER_CREDENTIALS = {
#     "admin": "password123"
# }

def require_login():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if not st.session_state["authenticated"]:
        st.subheader("🔐 Login")
        username = st.text_input("Usuario")
        password = st.text_input("Contraseña", type="password")
        if st.button("Ingresar"):
            if username in USER_CREDENTIALS and password == USER_CREDENTIALS[username]:
                st.session_state["authenticated"] = True
                if hasattr(st, "experimental_rerun"):
                    st.experimental_rerun()
                else:
                    st.rerun()
            else:
                st.error("Credenciales incorrectas")
        st.stop()

def logout_button():
    if st.session_state.get("authenticated") and st.sidebar.button("Cerrar sesión"):
        st.session_state.clear()
        if hasattr(st, "experimental_rerun"):
            st.experimental_rerun()
        else:
            st.rerun()


# --------------------------------------------------
# Helper functions
# --------------------------------------------------

def process_salary_data(pdf_path: str) -> pd.DataFrame:
    """Extrae y limpia el salario de jugadoras desde un PDF."""
    try:
        tables = tabula.read_pdf(
            pdf_path,
            pages=1,
            multiple_tables=True,
            pandas_options={"header": None},
            stream=True,
        )
    except Exception as e:
        st.warning(f"❌ Error leyendo {os.path.basename(pdf_path)}: {e}")
        return pd.DataFrame()

    if not tables:
        st.warning(f"⚠️  No se encontraron tablas en {os.path.basename(pdf_path)}")
        return pd.DataFrame()

    df = tables[0]

    player_rows = df[df[0].notna() & df[5].notna()].copy()
    player_rows = player_rows[
        ~player_rows[0].astype(str).str.contains("Last Name|Player", na=False)
    ]

    if player_rows.empty:
        st.warning(f"⚠️  No se detectaron filas de jugadoras en {os.path.basename(pdf_path)}")
        return pd.DataFrame()

    names = player_rows[0].astype(str)
    salaries = player_rows[5].astype(str)

    name_parts = names.str.rsplit(n=1, expand=True)
    cleaned_salaries = salaries.str.replace(r"[$,\s]", "", regex=True)
    numeric_salaries = pd.to_numeric(cleaned_salaries, errors="coerce")

    clean_df = pd.DataFrame(
        {
            "Last": name_parts[0],
            "First": name_parts[1],
            "Salary": numeric_salaries,
        }
    )
    clean_df.dropna(subset=["Last", "First", "Salary"], inplace=True)
    clean_df["Player"] = (
        clean_df["First"].str.strip().str[0] + ". " + clean_df["Last"].str.strip()
    )

    return clean_df[["Player", "Salary"]].rename(columns={"Salary": "2025 Salary"})


def standardize_excel_name(name: str):
    if not isinstance(name, str) or " " not in name:
        return None
    parts = name.split()
    return f"{parts[0][0]}. {parts[-1]}"

# --------------------------------------------------
# Streamlit UI
# --------------------------------------------------

require_login()
logout_button()

st.set_page_config(page_title="NWSL Salary Matcher", page_icon="⚽")
st.title("🔗 NWSL Salary Matcher")
st.write(
    "Sube tu archivo **Excel** con stats y uno o más **PDF** con las tablas de salarios.\n"
    "El sistema combinará la información y te permitirá descargar un Excel con: \n"
    "• Jugadoras matcheadas (stats + salario)\n"
    "• Jugadoras no matcheadas (salario sin stats)"
)

excel_file = st.file_uploader("📊 Excel de stats", type=["xlsx"])
pdf_files = st.file_uploader(
    "📄 PDFs de salarios (puedes seleccionar varios)",
    type=["pdf"],
    accept_multiple_files=True,
)

if excel_file and pdf_files:
    if st.button("Procesar datos"):
        salary_dfs = []
        for up_file in pdf_files:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(up_file.getbuffer())
                tmp_path = tmp.name
            df_salary = process_salary_data(tmp_path)
            os.unlink(tmp_path)
            if not df_salary.empty:
                team_name = os.path.splitext(up_file.name)[0].replace(
                    "April 2025 Salary Cap_", ""
                )
                df_salary["Team"] = team_name
                salary_dfs.append(df_salary)

        if not salary_dfs:
            st.error("Ningún PDF produjo datos válidos.")
            st.stop()

        df_salary_all = pd.concat(salary_dfs, ignore_index=True)

        try:
            df_stats = pd.read_excel(excel_file)
        except Exception as e:
            st.error(f"Error al leer el Excel de stats: {e}")
            st.stop()

        df_stats["Player_Key"] = df_stats["Player"].apply(standardize_excel_name)

        df_merged = pd.merge(
            df_salary_all,
            df_stats,
            left_on="Player",
            right_on="Player_Key",
            how="left",
        )
        df_merged.drop(columns=["Player_Key", "Player_y"], inplace=True, errors="ignore")
        df_merged.rename(columns={"Player_x": "Player"}, inplace=True)

        unmatched = df_merged[df_merged["Team_y"].isna()].copy()
        matched = df_merged[df_merged["Team_y"].notna()].copy()

        st.success(
            f"Procesado completo: {len(matched)} matcheadas, {len(unmatched)} no matcheadas"
        )

        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            matched.to_excel(writer, sheet_name="Matched", index=False)
            unmatched.to_excel(writer, sheet_name="Unmatched", index=False)
        output.seek(0)

        st.download_button(
            label="⬇️ Descargar resultado (Excel)",
            data=output,
            file_name="matched_salaries.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        st.subheader("Preview de datos matcheados")
        st.dataframe(matched.head())

        st.subheader("Preview de datos no matcheados")
        st.dataframe(unmatched.head())
else:
    st.info("Carga el Excel y al menos un PDF para comenzar.")
