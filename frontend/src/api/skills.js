import axios from 'axios'

const API_BASE_URL = import.meta.env.PROD
  ? 'https://contract-review-z9te.onrender.com/api/v3'
  : '/api/v3'

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

export async function fetchSkills(domainId = null) {
  const params = domainId ? { domain_id: domainId } : {}
  const response = await api.get('/skills', { params })
  return response.data
}

export async function fetchSkillDetail(skillId) {
  const response = await api.get(`/skills/${skillId}`)
  return response.data
}

export async function fetchSkillsByDomain(domainId) {
  const response = await api.get(`/skills/by-domain/${domainId}`)
  return response.data
}

export async function fetchDomains() {
  const response = await api.get('/domains')
  return response.data
}
