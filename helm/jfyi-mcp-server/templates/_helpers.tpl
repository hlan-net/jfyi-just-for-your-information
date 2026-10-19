{{/*
Expand the name of the chart.
*/}}
{{- define "jfyi-mcp-server.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "jfyi-mcp-server.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "jfyi-mcp-server.labels" -}}
helm.sh/chart: {{ include "jfyi-mcp-server.chart" . }}
{{ include "jfyi-mcp-server.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "jfyi-mcp-server.selectorLabels" -}}
app.kubernetes.io/name: {{ include "jfyi-mcp-server.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Chart label
*/}}
{{- define "jfyi-mcp-server.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
ServiceAccount name
*/}}
{{- define "jfyi-mcp-server.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "jfyi-mcp-server.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Name of the Secret aisa writes for this consumer (OPENAI_BASE_URL + OPENAI_API_KEY).
*/}}
{{- define "jfyi-mcp-server.aisaSecretName" -}}
{{- .Values.inference.aisa.secretName | default (printf "%s-aisa-key" (include "jfyi-mcp-server.fullname" .)) }}
{{- end }}

{{/*
Name of the Secret carrying direct inference credentials (chart-managed unless existingSecret is set).
*/}}
{{- define "jfyi-mcp-server.inferenceSecretName" -}}
{{- .Values.inference.direct.existingSecret | default (printf "%s-inference" (include "jfyi-mcp-server.fullname" .)) }}
{{- end }}
