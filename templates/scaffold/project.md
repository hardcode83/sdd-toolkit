# Project Steering

> Pendiente de generar. Ejecuta `/sdd:init` para rellenar este documento
> analizando el repositorio, o edítalo a mano.

## Overview

<!-- Qué es este proyecto, para quién, en una frase o dos. -->

## Stack

<!-- Lenguajes, frameworks, versiones relevantes, infra. -->

## Commands

<!-- Comandos exactos que el agente debe usar, descubiertos en este proyecto.
     No copies defaults from the toolkit: -->
<!-- build: -->
<!-- test: -->
<!-- lint: -->
<!-- run local: -->

## Worktree bootstrap

<!-- Qué necesita un worktree recién creado que git NO se lleva, y el comando
     exacto para conseguirlo. Sin esto, la verificación del proyecto falla dentro
     de un worktree y el fallo parece un problema de código (regla compartida 10).

     Rellena con lo que este proyecto necesite de verdad, p. ej.:
       - copiar `.env` desde el worktree principal
       - `make setup` / `npm ci` / `uv sync`
       - servicio compartido que ya corre en el principal (no duplicar puertos)

     Si no necesita nada, dilo explícitamente: un "nada que copiar" escrito vale
     más que una sección ausente, porque la fase siguiente ya tiene la respuesta.

     Si la verificación falla en un worktree por un fichero local que esta
     sección no menciona, eso ES el hallazgo: se documenta aquí, no se adivina. -->

## Conventions

<!-- Estructura de carpetas, patrones, estilo, cosas que NO hacer. -->

## Context

<!-- Enlaces: repo, CI, tickets, docs externas. MCPs/skills activados y para qué. -->
