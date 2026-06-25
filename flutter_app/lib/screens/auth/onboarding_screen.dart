import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../services/auth_service.dart';

class OnboardingScreen extends ConsumerWidget {
  const OnboardingScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authAsync = ref.watch(authNotifierProvider);
    final user = authAsync.value;

    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Spacer(),
              Text('Добро пожаловать!', style: Theme.of(context).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.bold, color: Colors.white)),
              const SizedBox(height: 8),
              Text(
                user?.username ?? '',
                style: Theme.of(context).textTheme.titleMedium?.copyWith(color: Colors.grey),
              ),
              const SizedBox(height: 48),

              if (user?.isPilot == true) ...[
                _RoleCard(
                  icon: Icons.sports_motorsports,
                  title: 'Вы — пилот',
                  subtitle: 'Смотрите свой рейтинг, результаты и личные рекорды',
                  color: const Color(0xFFE94560),
                ),
                const SizedBox(height: 16),
              ],

              if (user?.isManager == true) ...[
                _RoleCard(
                  icon: Icons.groups,
                  title: 'Вы — менеджер команды',
                  subtitle: 'Управляйте составом и следите за результатами команды',
                  color: const Color(0xFF0F3460),
                ),
                const SizedBox(height: 16),
              ],

              if (user?.isPilot == false && user?.isManager == false) ...[
                _RoleCard(
                  icon: Icons.favorite_outline,
                  title: 'Вы — болельщик',
                  subtitle: 'Следите за пилотами, результатами и новостями',
                  color: const Color(0xFF533483),
                ),
                const SizedBox(height: 16),
              ],

              const Spacer(flex: 2),
              ElevatedButton(
                onPressed: () => context.go('/feed'),
                child: const Text('Начать'),
              ),
              const SizedBox(height: 16),
            ],
          ),
        ),
      ),
    );
  }
}

class _RoleCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final Color color;

  const _RoleCard({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withOpacity(0.4)),
      ),
      child: Row(
        children: [
          Icon(icon, color: color, size: 36),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16)),
                const SizedBox(height: 4),
                Text(subtitle, style: TextStyle(color: Colors.grey[400], fontSize: 13)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
