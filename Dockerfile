# Using alpine for a smaller footprint
FROM nginx:alpine

# Copy custom Nginx configuration
COPY ./nginx/default.conf /etc/nginx/conf.d/default.conf

# Copy the static assets
COPY ./src/index.html /usr/share/nginx/html/index.html

# OpenShift normally runs containers as arbitrary non-root users.
# We must ensure that the directories Nginx needs to write to are accessible by the root group.
RUN touch /var/run/nginx.pid \
 && chgrp -R 0 /var/run/nginx.pid \
 && chmod -R g=u /var/run/nginx.pid \
 && chgrp -R 0 /var/cache/nginx \
 && chmod -R g=u /var/cache/nginx \
 && chgrp -R 0 /var/log/nginx \
 && chmod -R g=u /var/log/nginx

# Run as non-root user (1001 is a common safe substitute)
USER 1001

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
