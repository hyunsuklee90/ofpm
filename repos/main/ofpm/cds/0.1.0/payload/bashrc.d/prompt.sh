if [ -n "${CDS_LABEL:-}" ]; then
    export PS1="|\[\e[1;36m\]\t\[\e[0m\]|\u@${CDS_LABEL} \[\e[1;33m\]\W\[\e[0m\]\\$ "
else
    export PS1='|\[\e[1;36m\]\t\[\e[0m\]|\u@\h \[\e[1;33m\]\W\[\e[0m\]\$ '
fi
