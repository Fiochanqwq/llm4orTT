// Explicitly safe application errors; do not expose arbitrary provider messages.
export class UserInputError extends Error {
  constructor(code,message){super(message);this.name='UserInputError';this.code=code;}
}
