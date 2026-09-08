// Идентификаторы физлица: ИНН и СНИЛС. Показываются у МЧД, но НЕ обязательны:
// на Госуслугах их не требуют, и в графу можно поставить прочерк. Если же
// введены цифры — проверяем контрольные разряды, а не только длину:
// перестановка цифр самая частая ошибка ввода, и всплывает она уже отказом
// ФНС. Те же правила продублированы на сервере (requests_reg/validators.py).

const INN12_W11 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
const INN12_W12 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]

export function digitsOnly(value: string): string {
  return (value || '').replace(/\D/g, '')
}

/** «Значения нет»: пусто или прочерк.
 *
 * Для МЧД через Госуслуги ИНН и СНИЛС не нужны, и в такие графы по привычке
 * из бумажных бланков ставят «—», «-», «нет». Цифр нет — проверять нечего.
 * Ровно то же правило на сервере (requests_reg/validators.is_placeholder). */
export function isPlaceholder(value: string): boolean {
  return !digitsOnly(value)
}

function control(nums: number[], weights: number[]): number {
  return (nums.reduce((acc, n, i) => acc + n * weights[i], 0) % 11) % 10
}

/** ИНН физического лица — 12 цифр с двумя контрольными разрядами. */
export function isValidInn(value: string): boolean {
  const d = digitsOnly(value)
  if (d.length !== 12) return false
  const nums = [...d].map(Number)
  return control(nums.slice(0, 10), INN12_W11) === nums[10]
    && control(nums.slice(0, 11), INN12_W12) === nums[11]
}

/** СНИЛС — 11 цифр: 9 значащих + 2 контрольных (правило ПФР). */
export function isValidSnils(value: string): boolean {
  const d = digitsOnly(value)
  if (d.length !== 11) return false
  // номера до 001-001-998 контрольного числа не имеют
  if (Number(d.slice(0, 9)) <= 1001998) return true
  let sum = 0
  for (let i = 0; i < 9; i += 1) sum += Number(d[i]) * (9 - i)
  let checksum = sum % 101
  if (checksum === 100 || checksum === 101) checksum = 0
  return checksum === Number(d.slice(9))
}

/** СНИЛС в человеческом виде: XXX-XXX-XXX YY. */
export function formatSnils(value: string): string {
  const d = digitsOnly(value)
  if (d.length !== 11) return value
  return `${d.slice(0, 3)}-${d.slice(3, 6)}-${d.slice(6, 9)} ${d.slice(9)}`
}
