FROM nginx:alpine
# Landing institucional servida estaticamente em /
COPY site/ /var/www/site/
# Configs candidatos ficam FORA de conf.d (evita carga dupla / servidor duplicado)
COPY nginx/default.conf   /etc/nginx/candidates/default.conf
COPY nginx/bootstrap.conf /etc/nginx/candidates/bootstrap.conf
# O entrypoint copia APENAS um deles para conf.d/default.conf conforme o TLS
COPY nginx/entrypoint.sh /docker-entrypoint.d/50-select-config.sh
RUN chmod +x /docker-entrypoint.d/50-select-config.sh