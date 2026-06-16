#!/bin/bash
if [ "${CDS_ENABLE_ALIASES:-1}" != "1" ]; then
    return
fi

alias dir='dir --color=always'
alias rm='rm -i'
alias cp='cp -i'
alias mv='mv -i'
alias dir='dir --color=always'
alias ls='ls --color=auto'
alias ll='ls -lF'
