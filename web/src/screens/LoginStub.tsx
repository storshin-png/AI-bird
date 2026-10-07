type LoginStubProps = {
  onEnter: () => void;
};

export function LoginStub({ onEnter }: LoginStubProps) {
  return (
    <main className="login">
      <form
        className="login-card"
        onSubmit={(event) => {
          event.preventDefault();
          onEnter();
        }}
      >
        <p className="eyebrow">AI-bird</p>
        <h1>Вход</h1>
        <p className="note">Заглушка. Учётная запись на сервере не проверяется.</p>
        <label>
          Почта
          <input type="email" name="email" autoComplete="username" />
        </label>
        <label>
          Пароль
          <input type="password" name="password" autoComplete="current-password" />
        </label>
        <button type="submit">Войти</button>
      </form>
    </main>
  );
}
