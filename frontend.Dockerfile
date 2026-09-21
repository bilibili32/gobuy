FROM nginx:1.27-alpine

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/index.html /usr/share/nginx/html/index.html
COPY frontend/admin.html /usr/share/nginx/html/admin.html
COPY frontend/login.html /usr/share/nginx/html/login.html
COPY frontend/purchaser.html /usr/share/nginx/html/purchaser.html
COPY frontend/member.html /usr/share/nginx/html/member.html
COPY frontend/auth.js /usr/share/nginx/html/auth.js
COPY frontend/export.js /usr/share/nginx/html/export.js
COPY frontend/responsive.css /usr/share/nginx/html/responsive.css
COPY frontend/vendor /usr/share/nginx/html/vendor
