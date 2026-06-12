{{/* Expand the name of the chart. */}}
{{- define "ski.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "ski.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "ski.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "ski.labels" -}}
app.kubernetes.io/name: {{ include "ski.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/* Hard requirements — fail the render loudly, not the Pod at 3 a.m. */}}
{{- define "ski.validate" -}}
{{- if or (hasKey .Values "replicas") (hasKey .Values "replicaCount") -}}
{{- fail "The SKI Model is single-worker BY DESIGN (docs/CONCURRENCY.md): one Pod per ledger. replicas/replicaCount are not supported - shard by installing one release per shard." -}}
{{- end -}}
{{- if not .Values.image.repository -}}
{{- fail "image.repository is required: build reference-implementation/Dockerfile.ski-model and push it to your registry." -}}
{{- end -}}
{{- if not .Values.existingSecret -}}
{{- fail "existingSecret is required (keys: api-key, ledger-dsn; +postgres-password when postgres.bundled). This chart ships NO default secrets." -}}
{{- end -}}
{{- if not .Values.kg.configMapName -}}
{{- fail "kg.configMapName is required: create a ConfigMap/Secret holding your SIGNED Knowledge Graph as kg.json." -}}
{{- end -}}
{{- if and .Values.tls.enabled (not .Values.tls.secretName) -}}
{{- fail "tls.enabled=true requires tls.secretName (a kubernetes.io/tls Secret)." -}}
{{- end -}}
{{- if and (eq .Values.skiModel.backend "ollama") (not .Values.ollama.bundled) (not .Values.skiModel.externalOllamaUrl) -}}
{{- fail "backend=ollama needs ollama.bundled=true or skiModel.externalOllamaUrl." -}}
{{- end -}}
{{- if and (eq .Values.skiModel.backend "vllm") (not .Values.skiModel.externalVllmUrl) -}}
{{- fail "backend=vllm requires skiModel.externalVllmUrl (vLLM is not bundled; it needs your GPU node pool)." -}}
{{- end -}}
{{- end -}}

{{- define "ski.ollamaUrl" -}}
{{- if .Values.ollama.bundled -}}
http://{{ include "ski.fullname" . }}-ollama:11434
{{- else -}}
{{- .Values.skiModel.externalOllamaUrl -}}
{{- end -}}
{{- end -}}
