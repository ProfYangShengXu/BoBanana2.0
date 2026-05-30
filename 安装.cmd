@echo off
REM BoBanana 2.0 — 中文安装入口（与 install.cmd 相同）
title BoBanana 2.0 安装
cd /d "%~dp0"
call "%~dp0install.cmd" %*
