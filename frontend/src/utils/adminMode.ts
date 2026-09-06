// Флаг «режима администратора» в localStorage. Вынесен отдельно от стора,
// потому что его читает и слой api (services/api.ts): импорт стора оттуда
// замкнул бы цикл api → adminMode → auth → api.
//
// Флаг — только намерение клиента. Право проверяет сервер на каждом запросе
// (core.auth.is_admin_mode), поэтому подделка ключа ничего не даёт.
export const ADMIN_MODE_KEY = 'minised.adminMode'

export function readAdminMode(): boolean {
  try {
    return localStorage.getItem(ADMIN_MODE_KEY) === '1'
  } catch {
    return false // приватный режим / заблокированное хранилище
  }
}

export function writeAdminMode(on: boolean): void {
  try {
    localStorage.setItem(ADMIN_MODE_KEY, on ? '1' : '0')
  } catch { /* не критично: режим просто не переживёт перезагрузку */ }
}
