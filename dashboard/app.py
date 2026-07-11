import streamlit as st

st.set_page_config(
    page_title="Observatório Parlamentar",
    page_icon="🏛️",
    layout="wide",
)

st.title("Observatório Parlamentar")
st.markdown("Plataforma de Inteligência Parlamentar Brasileira")

st.markdown("---")
st.markdown("### Status dos Serviços")

col1, col2, col3 = st.columns(3)
col1.metric("API", "🟢 Online")
col2.metric("MinIO Storage", "🟢 Online")
col3.metric("Pipeline", "⏳ Pendente")

st.markdown("---")
st.info("Navegue pelas páginas no menu lateral para explorar os dados.")
