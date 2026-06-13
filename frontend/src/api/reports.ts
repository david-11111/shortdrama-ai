import client from './client'

export const reportsApi = {
  getUsage(days = 30) {
    return client.get('/reports/usage', { params: { days } })
  },
  getSummary() {
    return client.get('/reports/usage/summary')
  },
  getCreditsHistory(page = 1, page_size = 20) {
    return client.get('/reports/credits/history', { params: { page, page_size } })
  },
}
