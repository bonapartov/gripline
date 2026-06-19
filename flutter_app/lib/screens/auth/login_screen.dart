import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../services/auth_service.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _usernameCtrl = TextEditingController();
  final _passwordCtrl = TextEditingController();
  bool _obscure = true;

  @override
  void dispose() {
    _usernameCtrl.dispose();
    _passwordCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    await ref.read(authNotifierProvider.notifier).login(
          _usernameCtrl.text.trim(),
          _passwordCtrl.text,
        );
    if (!mounted) return;
    final authState = ref.read(authNotifierProvider);
    authState.whenOrNull(
      data: (user) {
        if (user != null) context.go('/feed');
      },
      error: (e, _) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e.toString()), backgroundColor: Colors.red),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final authState = ref.watch(authNotifierProvider);
    final isLoading = authState.isLoading;

    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Spacer(),
                Text('Gripline', style: Theme.of(context).textTheme.headlineLarge?.copyWith(fontWeight: FontWeight.bold, color: Colors.white)),
                const SizedBox(height: 4),
                Text('Карт-федерация', style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: Colors.grey)),
                const SizedBox(height: 48),
                TextFormField(
                  controller: _usernameCtrl,
                  decoration: const InputDecoration(labelText: 'Логин'),
                  textInputAction: TextInputAction.next,
                  validator: (v) => (v == null || v.isEmpty) ? 'Введите логин' : null,
                ),
                const SizedBox(height: 16),
                TextFormField(
                  controller: _passwordCtrl,
                  decoration: InputDecoration(
                    labelText: 'Пароль',
                    suffixIcon: IconButton(
                      icon: Icon(_obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                      onPressed: () => setState(() => _obscure = !_obscure),
                    ),
                  ),
                  obscureText: _obscure,
                  textInputAction: TextInputAction.done,
                  onFieldSubmitted: (_) => _submit(),
                  validator: (v) => (v == null || v.isEmpty) ? 'Введите пароль' : null,
                ),
                const SizedBox(height: 32),
                ElevatedButton(
                  onPressed: isLoading ? null : _submit,
                  child: isLoading
                      ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                      : const Text('Войти'),
                ),
                const Spacer(flex: 2),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
